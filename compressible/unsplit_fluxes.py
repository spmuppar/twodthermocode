"""
Implementation of the Colella 2nd order unsplit Godunov scheme.  This
is a 2-dimensional implementation only.  We assume that the grid is
uniform, but it is relatively straightforward to relax this
assumption.

There are several different options for this solver (they are all
discussed in the Colella paper).

  limiter          = 0 to use no limiting
                   = 1 to use the 2nd order MC limiter
                   = 2 to use the 4th order MC limiter

  riemann          = HLLC to use the HLLC solver
                   = CGF to use the Colella, Glaz, and Ferguson solver

  use_flattening   = 1 to use the multidimensional flattening
                     algorithm at shocks

  delta, z0, z1      these are the flattening parameters.  The default
                     are the values listed in Colella 1990.

   j+3/2--+---------+---------+---------+
          |         |         |         |
     j+1 _|         |         |         |
          |         |         |         |
          |         |         |         |
   j+1/2--+---------XXXXXXXXXXX---------+
          |         X         X         |
       j _|         X         X         |
          |         X         X         |
          |         X         X         |
   j-1/2--+---------XXXXXXXXXXX---------+
          |         |         |         |
     j-1 _|         |         |         |
          |         |         |         |
          |         |         |         |
   j-3/2--+---------+---------+---------+
          |    |    |    |    |    |    |
              i-1        i        i+1
        i-3/2     i-1/2     i+1/2     i+3/2

We wish to solve

  U_t + F^x_x + F^y_y = H

we want U_{i+1/2}^{n+1/2} -- the interface values that are input to
the Riemann problem through the faces for each zone.

Taylor expanding yields

   n+1/2                     dU           dU
  U          = U   + 0.5 dx  --  + 0.5 dt --
   i+1/2,j,L    i,j          dx           dt


                             dU             dF^x   dF^y
             = U   + 0.5 dx  --  - 0.5 dt ( ---- + ---- - H )
                i,j          dx              dx     dy


                              dU      dF^x            dF^y
             = U   + 0.5 ( dx -- - dt ---- ) - 0.5 dt ---- + 0.5 dt H
                i,j           dx       dx              dy


                                  dt       dU           dF^y
             = U   + 0.5 dx ( 1 - -- A^x ) --  - 0.5 dt ---- + 0.5 dt H
                i,j               dx       dx            dy


                                dt       _            dF^y
             = U   + 0.5  ( 1 - -- A^x ) DU  - 0.5 dt ---- + 0.5 dt H
                i,j             dx                     dy

                     +----------+-----------+  +----+----+   +---+---+
                                |                   |            |

                    this is the monotonized   this is the   source term
                    central difference term   transverse
                                              flux term

There are two components, the central difference in the normal to the
interface, and the transverse flux difference.  This is done for the
left and right sides of all 4 interfaces in a zone, which are then
used as input to the Riemann problem, yielding the 1/2 time interface
values,

     n+1/2
    U
     i+1/2,j

Then, the zone average values are updated in the usual finite-volume
way:

    n+1    n     dt    x  n+1/2       x  n+1/2
   U    = U    + -- { F (U       ) - F (U       ) }
    i,j    i,j   dx       i-1/2,j        i+1/2,j


                 dt    y  n+1/2       y  n+1/2
               + -- { F (U       ) - F (U       ) }
                 dy       i,j-1/2        i,j+1/2

Updating U_{i,j}:

  -- We want to find the state to the left and right (or top and
     bottom) of each interface, ex. U_{i+1/2,j,[lr]}^{n+1/2}, and use
     them to solve a Riemann problem across each of the four
     interfaces.

  -- U_{i+1/2,j,[lr]}^{n+1/2} is comprised of two parts, the
     computation of the monotonized central differences in the normal
     direction (eqs. 2.8, 2.10) and the computation of the transverse
     derivatives, which requires the solution of a Riemann problem in
     the transverse direction (eqs. 2.9, 2.14).

       -- the monotonized central difference part is computed using
          the primitive variables.

       -- We compute the central difference part in both directions
          before doing the transverse flux differencing, since for the
          high-order transverse flux implementation, we use these as
          the input to the transverse Riemann problem.
"""

import compressible.eos as eos
import compressible.interface_f as interface_f
import compressible as comp
import mesh.reconstruction as reconstruction
import mesh.reconstruction_f as reconstruction_f
import mesh.array_indexer as ai
from pdb import set_trace as keyboard
import numpy as np
import thermodynamics_tools as tools
from util import msg
from CoolProp.CoolProp import PropsSI
from CoolProp.CoolProp import PhaseSI
fluid = 'Nitrogen'
import preos_cy as PREOS
#import preos 
#PREOS = preos.peng_robinson_fluid()

def unsplit_fluxes(my_data, my_aux, rp, ivars, solid, tc, dt):
    """
    unsplitFluxes returns the fluxes through the x and y interfaces by
    doing an unsplit reconstruction of the interface values and then
    solving the Riemann problem through all the interfaces at once

    currently we assume a gamma-law EOS

    The runtime parameter grav is assumed to be the gravitational
    acceleration in the y-direction

    Parameters
    ----------
    my_data : CellCenterData2d object
        The data object containing the grid and advective scalar that
        we are advecting.
    rp : RuntimeParameters object
        The runtime parameters for the simulation
    vars : Variables object
        The Variables object that tells us which indices refer to which
        variables
    tc : TimerCollection object
        The timers we are using to profile
    dt : float
        The timestep we are advancing through.

    Returns
    -------
    out : ndarray, ndarray
        The fluxes on the x- and y-interfaces

    """

    tm_flux = tc.timer("unsplitFluxes")
    tm_flux.begin()

    myg = my_data.grid

    gamma = rp.get_param("eos.gamma")

    #=========================================================================
    # compute the primitive variables
    #=========================================================================
    # Q = (rho, u, v, p)

    dens = my_data.get_var("density")
    xmom = my_data.get_var("x-momentum")
    ymom = my_data.get_var("y-momentum")
    ener = my_data.get_var("energy")

    r, u, v, p = my_data.get_var("primitive")
    smallp = 1.e-10
    p = p.clip(smallp)   # apply a floor to the pressure


    #=========================================================================
    # compute the flattening coefficients
    #=========================================================================

    # there is a single flattening coefficient (xi) for all directions
    use_flattening = rp.get_param("compressible.use_flattening")

    if use_flattening:
        delta = rp.get_param("compressible.delta")
        z0 = rp.get_param("compressible.z0")
        z1 = rp.get_param("compressible.z1")

        xi_x = reconstruction_f.flatten(1, p, u, myg.qx, myg.qy, myg.ng, smallp, delta, z0, z1)
        xi_y = reconstruction_f.flatten(2, p, v, myg.qx, myg.qy, myg.ng, smallp, delta, z0, z1)

        xi = reconstruction_f.flatten_multid(xi_x, xi_y, p, myg.qx, myg.qy, myg.ng)
    else:
        xi = 1.0


    # monotonized central differences in x-direction
    tm_limit = tc.timer("limiting")
    tm_limit.begin()

    limiter = rp.get_param("compressible.limiter")

    ldelta_rx = xi*reconstruction.limit(r, myg, 1, limiter)
    ldelta_ux = xi*reconstruction.limit(u, myg, 1, limiter)
    ldelta_vx = xi*reconstruction.limit(v, myg, 1, limiter)
    ldelta_px = xi*reconstruction.limit(p, myg, 1, limiter)

    # monotonized central differences in y-direction
    ldelta_ry = xi*reconstruction.limit(r, myg, 2, limiter)
    ldelta_uy = xi*reconstruction.limit(u, myg, 2, limiter)
    ldelta_vy = xi*reconstruction.limit(v, myg, 2, limiter)
    ldelta_py = xi*reconstruction.limit(p, myg, 2, limiter)

    tm_limit.end()


    #=========================================================================
    # x-direction
    #=========================================================================

    # left and right primitive variable states
    tm_states = tc.timer("interfaceStates")
    tm_states.begin()

    V_l, V_r = interface_f.states(1, myg.qx, myg.qy, myg.ng, myg.dx, dt,
                                  ivars.nvar,
                                  speed,
                                  r, u, v, p,
                                  ldelta_rx, ldelta_ux, ldelta_vx, ldelta_px)

    tm_states.end()

    # transform interface states back into conserved variables
    U_xl = comp.prim_to_cons(V_l, gamma, ivars, myg)
    U_xr = comp.prim_to_cons(V_r, gamma, ivars, myg)

    #=========================================================================
    # y-direction
    #=========================================================================


    # left and right primitive variable states
    tm_states.begin()

    V_l, V_r = interface_f.states(2, myg.qx, myg.qy, myg.ng, myg.dy, dt,
                                  ivars.nvar,
                                  speed,
                                  r, u, v, p,
                                  ldelta_ry, ldelta_uy, ldelta_vy, ldelta_py)

    tm_states.end()


    # transform interface states back into conserved variables
    U_yl = comp.prim_to_cons(V_l, gamma, ivars, myg)
    U_yr = comp.prim_to_cons(V_r, gamma, ivars, myg)

    #=========================================================================
    # apply source terms
    #=========================================================================
    grav = rp.get_param("compressible.grav")

    ymom_src = my_aux.get_var("ymom_src")
    ymom_src.v()[:,:] = dens.v()*grav
    my_aux.fill_BC("ymom_src")

    E_src = my_aux.get_var("E_src")
    E_src.v()[:,:] = ymom.v()*grav
    my_aux.fill_BC("E_src")

    # ymom_xl[i,j] += 0.5*dt*dens[i-1,j]*grav
    U_xl.v(buf=1, n=ivars.iymom)[:,:] += 0.5*dt*ymom_src.ip(-1, buf=1)
    U_xl.v(buf=1, n=ivars.iener)[:,:] += 0.5*dt*E_src.ip(-1, buf=1)

    # ymom_xr[i,j] += 0.5*dt*dens[i,j]*grav
    U_xr.v(buf=1, n=ivars.iymom)[:,:] += 0.5*dt*ymom_src.v(buf=1)
    U_xr.v(buf=1, n=ivars.iener)[:,:] += 0.5*dt*E_src.v(buf=1)

    # ymom_yl[i,j] += 0.5*dt*dens[i,j-1]*grav
    U_yl.v(buf=1, n=ivars.iymom)[:,:] += 0.5*dt*ymom_src.jp(-1, buf=1)
    U_yl.v(buf=1, n=ivars.iener)[:,:] += 0.5*dt*E_src.jp(-1, buf=1)

    # ymom_yr[i,j] += 0.5*dt*dens[i,j]*grav
    U_yr.v(buf=1, n=ivars.iymom)[:,:] += 0.5*dt*ymom_src.v(buf=1)
    U_yr.v(buf=1, n=ivars.iener)[:,:] += 0.5*dt*E_src.v(buf=1)


    #=========================================================================
    # compute transverse fluxes
    #=========================================================================
    tm_riem = tc.timer("riemann")
    tm_riem.begin()

    riemann = rp.get_param("compressible.riemann")
    riemann = "CGF"
    if riemann == "HLLC":
        riemannFunc = interface_f.riemann_hllc
    elif riemann == "CGF":
        riemannFunc = interface_f.riemann_cgf
    else:
        msg.fail("ERROR: Riemann solver undefined")

    _fx = riemannFunc(1, myg.qx, myg.qy, myg.ng,
                      ivars.nvar, ivars.idens, ivars.ixmom, ivars.iymom, ivars.iener,
                      solid.xl, solid.xr,
                      real_gamma, pres, U_xl, U_xr)

    _fy = riemannFunc(2, myg.qx, myg.qy, myg.ng,
                      ivars.nvar, ivars.idens, ivars.ixmom, ivars.iymom, ivars.iener,
                      solid.yl, solid.yr,
                      real_gamma, pres, U_yl, U_yr)

    F_x = ai.ArrayIndexer(d=_fx, grid=myg)
    F_y = ai.ArrayIndexer(d=_fy, grid=myg)    
    
    tm_riem.end()
    #keyboard()
    #=========================================================================
    # construct the interface values of U now
    #=========================================================================

    """
    finally, we can construct the state perpendicular to the interface
    by adding the central difference part to the trasverse flux
    difference.

    The states that we represent by indices i,j are shown below
    (1,2,3,4):


      j+3/2--+----------+----------+----------+
             |          |          |          |
             |          |          |          |
        j+1 -+          |          |          |
             |          |          |          |
             |          |          |          |    1: U_xl[i,j,:] = U
      j+1/2--+----------XXXXXXXXXXXX----------+                      i-1/2,j,L
             |          X          X          |
             |          X          X          |
          j -+        1 X 2        X          |    2: U_xr[i,j,:] = U
             |          X          X          |                      i-1/2,j,R
             |          X    4     X          |
      j-1/2--+----------XXXXXXXXXXXX----------+
             |          |    3     |          |    3: U_yl[i,j,:] = U
             |          |          |          |                      i,j-1/2,L
        j-1 -+          |          |          |
             |          |          |          |
             |          |          |          |    4: U_yr[i,j,:] = U
      j-3/2--+----------+----------+----------+                      i,j-1/2,R
             |    |     |    |     |    |     |
                 i-1         i         i+1
           i-3/2      i-1/2      i+1/2      i+3/2


    remember that the fluxes are stored on the left edge, so

    F_x[i,j,:] = F_x
                    i-1/2, j

    F_y[i,j,:] = F_y
                    i, j-1/2

    """

    tm_transverse = tc.timer("transverse flux addition")
    tm_transverse.begin()

    dtdx = dt/myg.dx
    dtdy = dt/myg.dy
    
    b = (2,1)

    for n in range(ivars.nvar):
            
        # U_xl[i,j,:] = U_xl[i,j,:] - 0.5*dt/dy * (F_y[i-1,j+1,:] - F_y[i-1,j,:])
        U_xl.v(buf=b, n=n)[:,:] += \
            - 0.5*dtdy*(F_y.ip_jp(-1, 1, buf=b, n=n) - F_y.ip(-1, buf=b, n=n))

        # U_xr[i,j,:] = U_xr[i,j,:] - 0.5*dt/dy * (F_y[i,j+1,:] - F_y[i,j,:])
        U_xr.v(buf=b, n=n)[:,:] += \
            - 0.5*dtdy*(F_y.jp(1, buf=b, n=n) - F_y.v(buf=b, n=n))

        # U_yl[i,j,:] = U_yl[i,j,:] - 0.5*dt/dx * (F_x[i+1,j-1,:] - F_x[i,j-1,:])
        U_yl.v(buf=b, n=n)[:,:] += \
            - 0.5*dtdx*(F_x.ip_jp(1, -1, buf=b, n=n) - F_x.jp(-1, buf=b, n=n))

        # U_yr[i,j,:] = U_yr[i,j,:] - 0.5*dt/dx * (F_x[i+1,j,:] - F_x[i,j,:])
        U_yr.v(buf=b, n=n)[:,:] += \
            - 0.5*dtdx*(F_x.ip(1, buf=b, n=n) - F_x.v(buf=b, n=n))
        
    tm_transverse.end()


    #=========================================================================
    # construct the fluxes normal to the interfaces
    #=========================================================================

    # up until now, F_x and F_y stored the transverse fluxes, now we
    # overwrite with the fluxes normal to the interfaces
    #keyboard()
    tm_riem.begin()

    _fx = riemannFunc(1, myg.qx, myg.qy, myg.ng,
                      ivars.nvar, ivars.idens, ivars.ixmom, ivars.iymom, ivars.iener,
                      solid.xl, solid.xr,
                      real_gamma, pres, U_xl, U_xr)

    _fy = riemannFunc(2, myg.qx, myg.qy, myg.ng,
                      ivars.nvar, ivars.idens, ivars.ixmom, ivars.iymom, ivars.iener,
                      solid.yl, solid.yr,
                      real_gamma, pres, U_yl, U_yr)

    F_x = ai.ArrayIndexer(d=_fx, grid=myg)
    F_y = ai.ArrayIndexer(d=_fy, grid=myg)
    
    tm_riem.end()
    #keyboard()
    #=========================================================================
    # apply artificial viscosity
    #=========================================================================
    cvisc = rp.get_param("compressible.cvisc")

    _ax, _ay = interface_f.artificial_viscosity( 
        myg.qx, myg.qy, myg.ng, myg.dx, myg.dy, 
        cvisc, u, v)

    avisco_x = ai.ArrayIndexer(d=_ax, grid=myg)
    avisco_y = ai.ArrayIndexer(d=_ay, grid=myg)    
    
    b = (2,1)
    
    for n in range(ivars.nvar):
        # F_x = F_x + avisco_x * (U(i-1,j) - U(i,j))
        var = my_data.get_var_by_index(n)

        F_x.v(buf=b, n=n)[:,:] += \
            avisco_x.v(buf=b)*(var.ip(-1, buf=b) - var.v(buf=b))

        # F_y = F_y + avisco_y * (U(i,j-1) - U(i,j))
        F_y.v(buf=b, n=n)[:,:] += \
            avisco_y.v(buf=b)*(var.jp(-1, buf=b) - var.v(buf=b))

    tm_flux.end()
    #keyboard()
    return F_x, F_y

eqnst = 'coolprop'

if eqnst == 'PREOS':

  def pres(densener):
    densener[1] = tools.convertMassToMolar(densener[1], 28.0134)
    T_in = PREOS.getTfromEandRho(densener[1],densener[0])
    p = PREOS.getPfromTandRho(T_in, densener[0])

    #pressure = PropsSI('P', 'UMASS', densener[1],'DMASS', densener[0], fluid)
    #pressure = np.array(pressure, order = 'F')
    return p

  def real_gamma(denspres):
    #T_in = PREOS.getTfromPandRho(denspres[1], denspres[0])
    sos = PREOS.getSos([denspres[1], denspres[0]])

    #sos = PropsSI('A', 'P', denspres[1], 'DMASS', denspres[0], fluid)
    rg = np.array((sos**2)*denspres[0]/denspres[1], order = 'F')
    return rg

  def speed(prho):
    #print prho
    #T_in = PREOS.getTfromPandRho(prho[1], prho[0])
    sos = PREOS.getSos([prho[0], prho[1]])

    #sos = PropsSI('A', 'P', prho[0], 'DMASS', prho[1], "Oxygen")
    #sos = np.array(sos, order = 'F')
    return sos

elif eqnst == 'coolprop':

  def pres(densener):
    # MW = 28.0314
    # vol = tools.getVfromRho(densener[0], MW)
    # keyboard()
    # T_in = PREOS.NewtonIterate_TemperaturefromEv(densener[1],vol, T_in,eps=1E-6,omega=1.0)
    # p = PREOS.getPressurefromVolumeTemperature(vol,T_in)
    pressure = PropsSI('P', 'UMASS', densener[1],'DMASS', densener[0], fluid)
    #pressure = np.array(pressure, order = 'F')
    #print "The thermodynamic state is, ", densener, 
    #print "Pressure: ", pressure
    return pressure

  def real_gamma(denspres):
    #print "[ density, pressure ]"
    #print denspres
    #T_in = PREOS.NewtonIterate_TemperaturefromPrho(denspres[0], denspres[1], T_in = 300.0, eps= 1E-10, omega = 1.0)
    #sos = PREOS.getSpeedOfSound(denspres[1], T_in)
    sos = PropsSI('A', 'P', denspres[1], 'DMASS', denspres[0], fluid)
    rg = np.array((sos**2)*denspres[0]/denspres[1], order = 'F')
    return rg

  def speed(prho):
    #T_in = PREOS.NewtonIterate_TemperaturefromPrho(prho[1], prho[0], T_in = 300.0, eps= 1E-10, omega = 1.0)
    #sos = PREOS.getSpeedOfSound(prho[0], T_in)
    sos = PropsSI('A', 'P', prho[0], 'DMASS', prho[1], fluid)
    sos = np.array(sos, order = 'F')
    return sos

elif eqnst == 'ideal':

  def pres(densener):
    rhoe_l = densener[0]*densener[1]
    pressure = rhoe_l*(1.4 - 1.0)

    return pressure

  def real_gamma(denspres):
    rg = 1.4
    return rg

  def speed(prho):
    sos = np.sqrt(1.4*prho[0]/prho[1])
    return sos