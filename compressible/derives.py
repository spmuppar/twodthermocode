import numpy as np
from pdb import set_trace as keyboard
import compressible.eos as eos

def derive_primitives(myd, varnames):
    """ 
    derive desired primitive variables from conserved state
    """

    # get the variables we need
    dens = myd.get_var("density")
    xmom = myd.get_var("x-momentum")
    ymom = myd.get_var("y-momentum")
    ener = myd.get_var("energy")

    derived_vars = []

    u = xmom/dens
    v = ymom/dens

    e = (ener - 0.5*dens*(u*u + v*v))/dens

    gamma = myd.get_aux("gamma")
    p = eos.pres(dens, e)
    # to import the class attributes
    p = p*dens/dens
    if isinstance(varnames, str):
        wanted = [varnames]
    else:
        wanted = list(varnames)

    for var in wanted:

        if var == "velocity":
            derived_vars.append(u)
            derived_vars.append(v)

        elif var in ["e", "eint"]:
            keyboard()
            derived_vars.append(e)

        elif var in ["p", "pressure"]:
            derived_vars.append(p)

        elif var == "primitive":
            derived_vars.append(dens)
            derived_vars.append(u)
            derived_vars.append(v)
            derived_vars.append(p)

        elif var == "soundspeed":
            derived_vars.append(eos.sound(p, dens))


    if len(derived_vars) > 1:
        return derived_vars
    else:
        return derived_vars[0]

