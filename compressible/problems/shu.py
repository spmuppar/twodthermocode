from __future__ import print_function

import sys

import mesh.patch as patch
from util import msg
from pdb import set_trace as keyboard
import numpy as np
import compressible.eos as eos

def init_data(my_data, rp):
    """ initialize the sod problem """

    msg.bold("initializing the shu_osher problem...")

    # make sure that we are passed a valid patch object
    if not isinstance(my_data, patch.CellCenterData2d):
        print("ERROR: patch invalid in shu.py")
        print(my_data.__class__)
        sys.exit()


    # get the sod parameters
    dens_left = rp.get_param("sod.dens_left")
    dens_right = rp.get_param("sod.dens_right")

    u_left = rp.get_param("sod.u_left")
    u_right = rp.get_param("sod.u_right")

    p_left = rp.get_param("sod.p_left")
    p_right = rp.get_param("sod.p_right")
    

    # get the density, momenta, and energy as separate variables
    dens = my_data.get_var("density")
    xmom = my_data.get_var("x-momentum")
    ymom = my_data.get_var("y-momentum")
    ener = my_data.get_var("energy")

    # initialize the components, remember, that ener here is rho*eint
    # + 0.5*rho*v**2, where eint is the specific internal energy
    # (erg/g)
    xmin = rp.get_param("mesh.xmin")
    xmax = rp.get_param("mesh.xmax")

    ymin = rp.get_param("mesh.ymin")
    ymax = rp.get_param("mesh.ymax")

    gamma = rp.get_param("eos.gamma")

    direction = rp.get_param("sod.direction")
    
    #xctr = 0.5*(xmin + xmax)
    xctr = -0.4
    #yctr = -0.4
    yctr = 0.5*(ymin + ymax)

    myg = my_data.grid
    
    if direction == "x":

        # left
        idxl = myg.x2d < xctr

        dens[idxl] = dens_left
        xmom[idxl] = dens_left*u_left
        ymom[idxl] = 0.0
        ener[idxl] = p_left/(gamma - 1.0) + 0.5*xmom[idxl]*u_left

        # right
        idxr = myg.x2d >= xctr

        xdat = idxr[:,0]
        xall = myg.x2d[:,0]
        #rhocrit = dens_left/3.857
        rhocrit = 50.0

        for i in range(xdat.shape[0]):
            if idxr[i].all() == True:
                dens[i] = (1 + 0.2*np.sin(50.0*xall[i]))*rhocrit*np.ones(18)
                xmom[i] = (1 + 0.2*np.sin(50.0*xall[i]))*rhocrit*np.ones(18)*u_right
                ymom[i] = np.ones(18)*0.0
                #ener[i] = p_right/(gamma - 1.0) + 0.5*xmom[i]*u_right
                ener[i] = eos.rhoe((1.0 + 0.2*np.sin(50.0*xall[i]))*rhocrit*np.ones(18), p_right*np.ones(18)) + 0.5*xmom[i]*u_left
                
        # dens[idxr] = dens_right
        # xmom[idxr] = dens_right*u_right
        # ymom[idxr] = 0.0
        # ener[idxr] = p_right/(gamma - 1.0) + 0.5*xmom[idxr]*u_right

    else:

        # bottom
        idxb = myg.y2d < yctr

        dens[idxb] = dens_left
        xmom[idxb] = 0.0
        ymom[idxb] = dens_left*u_left
        ener[idxb] = p_left/(gamma - 1.0) + 0.5*ymom[idxb]*u_left
                
        # top
        idxt = myg.y2d >= yctr
        xdat = idxt[0]
        xall = myg.y2d[0]
        #rhocrit = dens_left/3.857
        rhocrit = 50.0
        for i in range(xdat.shape[0]):
            if idxt[:,i].all() == True:
                dens[:,i] = (1 + 0.2*np.sin(50.0*xall[i]))*rhocrit*np.ones(18)
                xmom[:,i] = (1 + 0.2*np.sin(50.0*xall[i]))*rhocrit*np.ones(18)*u_right
                ymom[:,i] = np.ones(18)*0.0
                #ener[:,i] = p_right/(gamma - 1.0) + 0.5*xmom[:,i]*u_right
                ener[:,i] = eos.rhoe(dens[:,i], p_right*np.ones(18)) + 0.5*xmom[:,i]*u_right
        # dens[idxt] = dens_right
        # xmom[idxt] = 0.0
        # ymom[idxt] = dens_right*u_right
        # ener[idxt] = p_right/(gamma - 1.0) + 0.5*ymom[idxt]*u_right
        
    
def finalize():
    """ print out any information to the user at the end of the run """

    msg = """
          The script analysis/sod_compare.py can be used to compare 
          this output to the exact solution.  Some sample exact solution
          data is present as analysis/sod-exact.out
          """

    print(msg)



                             
