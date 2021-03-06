import numpy as np
from pdb import set_trace as keyboard
import thermodynamics_tools as tools

def getThermo(T):
	#function [ a,b,R,dadT,d2adT2 ] = getThermo( T )
	#% getThermo Compute necessary thermodyamic parameters for the cubic
	#% equation of state (N2 property is assumed).

	# N2

	cdef float MW, pc, rhoc, omega, c, R, b

	MW   = 28.0134e-3
	#Tc   = 126.19
	pc   = 3.3958e+6
	rhoc = 313.3
	omega= 0.03720

	Tc = np.asarray(126.19)

	c = 0.37464 + 1.54226*omega - 0.26992*omega**2

	R = 8.314/MW
	#kappa = 0.37464 + 1.54226*omega-0.26992*omega**2
	#alpha = (1.0 + kappa*(1.0-(T/Tc)**0.5))**2
	#a = (0.457236 * alpha * (R*Tc)**2/pc)

	a = 0.457236*pow(R*Tc, 2) / pc*(1+c*(1-np.sqrt(T/Tc)))**2
	b = 0.077796*R*Tc/pc
	G = c*np.sqrt(T/Tc) / (1+c*(1-np.sqrt(T/Tc)))
	dadT = pow(T*a*G, -1)
	d2adT2 = np.asarray(0.457236*pow(R, 2)) / T/2*c*(1+c)*Tc/pc*np.sqrt(Tc/T)

	return a,b,R,dadT,d2adT2

def getEnergyfromTandRho(T, rho):

	# getEnergyfromTandRho Compute specific internal energy given temperature
	# and density. NASA polynomial for N2 is used.

	# nasa polynomial for N2
	coef = np.asarray([3.531005280E+00,-1.236609870E-04,-5.029994370E-07,2.435306120E-09, -1.408812350E-12,-1.046976280E+03,2.967474680E+00])
	 
	a,b,R,dadT,d2adT2 = getThermo(T)
	h_ideal = T*np.asarray(R)*(coef[0] + coef[1]*T/2.0 + coef[2]*pow(T,2)/3.0 + coef[3]*pow(T,3)/4.0 + coef[4] * pow(T,4)/5.0+ coef[5] / T)

	v = 1/rho
	K1 = 1.0/(2.0*np.sqrt(2.0)*b) * np.log((v+(1.0-np.sqrt(2))*b)/(v+(1.0+np.sqrt(2))*b))
	dep = (a - T*dadT)*K1

	e = h_ideal - R*T + dep

	return e

def getGamma(V):
	#function [ gammaS,e0S ] = getGammaSandE0S( V )
	# getGammaSandE0S Compute effective specific heat ratio and effective
	# reference energy for the double-flux model.

	rho = V[0]
	p = V[1]
	T = getTfromPandRho(p,rho)
	e = getEnergyfromTandRho(T,rho)

	sos = getSos(V)

	gammaS = sos**2*rho/p
	#e0S = e - p./rho./(gammaS-1)

	return gammaS

def getPfromTandRho(T,rho):
	#function [ p ] = getPfromTandRho( T,rho )
	#getPfromTandRho Compute pressure given temperature and density

	a,b,R,dadT,d2adT2 = getThermo(T) #R is in J/Kg K

	#v = tools.getVfromRho(rho, 28.0134e-3)
	v = 1.0/rho
	#p = R*T/(v-b) - a/(v**2+2*v*b-b**2)
	p = (R*T/(v-b))-(a/(v**2 + 2*v*b - b**2))

	return p

def getSos(V):
	# function [ sos ] = getSos( V )
	# % getSos Compute speed of sound given primitive variables. NASA polynomial
	# % for N2 is used.

	# nasa polynomial for N2
	coef = [3.531005280E+00,-1.236609870E-04,-5.029994370E-07,2.435306120E-09, -1.408812350E-12,-1.046976280E+03,2.967474680E+00]

	rho = V[1]
	p = V[0]
	v = 1./rho

	T = getTfromPandRho(p,rho)
	a,b,R,dadT,d2adT2 = getThermo(T)
	cp_ideal = R*(coef[0]  + coef[1]*T + coef[2]*T**2  + coef[3]*T**3  + coef[4]*T**4 )
	cv_ideal = cp_ideal - R

	dpdT = R/(v-b) - dadT/(v**2+2*v*b-b**2)
	coef = R*T/(v-b)**2
	para = (R*T*(v+b)*(v/(v-b)+ b/(v+b))**2)
	dpdv = -coef * (1.0 - 2.0*a/para)
	K1 = 1.0/(2.0*np.sqrt(2.0)*b) * np.log((v+(1.0-np.sqrt(2))*b)/(v+(1.0+np.sqrt(2))*b))
	cp = cv_ideal - T*(dpdT)**2 / dpdv - K1*T*d2adT2

	kT = -1./v/dpdv
	av = -dpdT/v/dpdv
	ks = kT - v*T*av**2./cp

	sos = np.sqrt(1./rho/ks)

	return sos


def getTfromPandRho(p,rho):
	#function [ T ] = getTfromPandRho( p,rho )
	# getTfromPandRho Compute temperature given pressure and density.

	cdef float CRIT
	CRIT = 1.0e-2

	v = 1./rho
	T = 300.0*np.ones(np.size(rho))
	p_n = getPfromTandRho(T,rho)
	diff = p_n - p

	while (max(abs(diff)) > CRIT):
		a,b,R,dadT,d2adT2 = getThermo(T)
		dpdT = R/(v-b) - 1./(v**2+2*v*b-b**2)*dadT
		T = T - diff/dpdT
		p_n = getPfromTandRho(T,rho)
		diff = p_n - p
	return T

def getTfromEandRho(double[:] e, rho):
	#function [ T ] = getTfromEandRho( eint,rho )
	# getTfromEandRho Compute temperature given pressure and density.

	cdef float CRIT = 0.001, R, b
	#CRIT = 1.0e-2
	cdef double[:] v, T, e_n, diff, a, dadT,d2adT2, dpdT
	v = pow(rho, -1)
	T = 300.0*np.ones(np.size(rho))
	e_n = getEnergyfromTandRho(T,rho)
	diff = np.asarray(e_n) - np.asarray(e)



	while (max(abs(diff)) > CRIT):
		a,b,R,dadT,d2adT2 = getThermo(T)
		dpdT = {R}/(v-{b}) - {1.0}/(pow(v,2)+{2.0}*v*{b}-{pow(b,2)})*dadT
		T = np.asarray(T) - (diff/np.asarray(dpdT))
		e_n = getEnergyfromTandRho(T,rho)
		diff = np.asarray(e_n) - np.asarray(e)
	return T


