from __future__ import print_function
import scipy.optimize as op
import numpy as np

class MMNModel:
    """
    This object creates a model comprised of multiple Miyamoto Nagai disks fitting a given potential.
    """
    def __init__(self, diz=1.0):
        """
        Constructor for the multi miyamoto nagai disk model
        :param diz: Normalization factor applied to all the models
        """
        # The disks and fit description
        self.models = []
        self.axes = []
        self.diz = diz

        # The data the model is fitting
        self.data = None
        self.yerr = None
        self.n_values = 0

    def add_model(self, axis, a, b, M):
        """
        This function adds a disk to the model. The disk, lies on a plane normal to "axis"
        A model is a list of three values a, b, M. Those values are all stored in line with no real separation. This is
        done so that emcee can be fed the array directly without any transformation.
        :param axis: the normal axis of the plane for the disk. The axis is a string and can be "x", "y" or "z"
        :param a: disk scale
        :param b: disk height
        :param M: model amplitude
        """
        self.models += [a, b, M]
        self.axes.append(axis)

    def add_models(self, values):
        """
        This function wraps the previous method to add multiple axes at the same time
        :param values: a list of 4-tuples : (axis, a, b, M). axis is a string indicating the normal vector to the plane
        of the disk to add. Can be : "x", "y" or "z"
        """
        for axis, a, b, M in values:
            self.add_model(axis, a, b, M)

    def get_models(self):
        """
        Copies the models currently stored and returns them
        :return: a list of models.
        """
        # Grouping the models
        res = []
        for id_axis, axis in enumerate(self.axes):
            res += [[axis] + self.models[id_axis*3:(id_axis+1)*3]]
        return res

    @staticmethod
    def mn_density(r, z, a, b, Mo):
        """
        Returns the Miyamoto Nagai density at polar coordinates (r, z).

        :param r: radius of the point where the density is evaluated
        :param z: height of the point where the density is evaluated
        :param a: disk scale
        :param b: disk height
        :param Mo: model amplitude
        """
        M = np.sqrt(Mo**2)
        h = np.sqrt((z**2)+(b**2))
        ah2 = (a+h)**2
        ar2 = a*(r**2)
        a3h = a+(3*h)
        num = ar2+(a3h*ah2)
        den = (h**3)*((r**2)+ah2)**2.5
        fac = (b**2)*M/(4*np.pi)
        return fac*num/den

    @staticmethod
    def mn_potential(r, z, a, b, Mo):
        """
        Returns the Miyamoto Nagai potential at polar coordinates (r, z)
        :param r: radius of the point where the density is evaluated
        :param z: height of the point where the density is evaluated
        :param a: disk scale
        :param b: disk height
        :param Mo: model amplitude
        """
        G = 0.0043008211
        kpc = 1000.0
        M = np.sqrt(Mo**2)
        h = np.sqrt(z**2 + b**2)
        den = r**2 + (a + h)**2
        return -G*M / np.sqrt(den)

    @staticmethod
    def mn_forceR(r, z, ao, bo, Mo):
        """
        Returns the radial component of Miyamoto Nagai force applied at polar coordinates (r, z)
        :param r: radius of the point where the density is evaluated
        :param z: height of the point where the density is evaluated
        :param a: disk scale
        :param b: disk height
        :param Mo: model amplitude
        """
        G = 0.0043008211
        kpc = 1000.0
        M = np.sqrt(Mo**2)
        rp=r*kpc
        zp=z*kpc
        a = ao*kpc
        b = bo*kpc
        h = np.sqrt(zp**2 + b**2)
        den = (rp**2 + (a + h)**2)**1.5
        return -G*M*rp/den

    @staticmethod
    def mn_forceV(r, z, ao, bo, Mo):
        """
        Returns the vertical comonent of Miyamoto Nagai force applied at polar coordinates (r, z)
        :param r: radius of the point where the density is evaluated
        :param z: height of the point where the density is evaluated
        :param a: disk scale
        :param b: disk height
        :param Mo: model amplitude
        """
        G = 0.0043008211
        kpc = 1000.0
        M = np.sqrt(Mo**2)
        rp=r*kpc
        zp=z*kpc
        a = ao*kpc
        b = bo*kpc
        h = np.sqrt(zp**2 + b**2)
        den = (rp**2 + (a + h)**2)**1.5
        num = G*M*zp
        fac = (a+h)/h
        return -fac*num/den

    @staticmethod
    def mn_circular_velocity(r, z, ao, bo, Mo):
        """
        Returns the radial component of Miyamoto Nagai force applied at polar coordinates (r, z)
        :param r: radius of the point where the density is evaluated
        :param z: height of the point where the density is evaluated
        :param a: disk scale
        :param b: disk height
        :param Mo: model amplitude
        """
        G = 0.0043008211
        kpc = 1000.0
        M = np.sqrt(Mo**2)
        rp=r*kpc
        zp=z*kpc
        a = ao*kpc
        b = bo*kpc
        h = np.sqrt(zp**2 + b**2)
        den = (rp**2 + (a + h)**2)**1.5
        return r*np.sqrt(G*M/den)

    def _evaluate_quantity(self, x, y, z, quantity_callback):
        """
        Generic private function to evaluate a quantity at a specific point of space
        :param x:
        :param y:
        :param z:
        :param quantity_callback: a function callback indicating which function is used to evaluate the quantity
        :return: the quantities evaluated at each points given in entry
        """
        # Radius on each plane
        rxy = np.sqrt(x**2+y**2)
        rxz = np.sqrt(x**2+z**2)
        ryz = np.sqrt(y**2+z**2)

        # Storing the first value firectly as the output variable. This allows us to avoid testing for scalar or vector
        # while initializing the total_sum variable
        a, b, M = self.models[0:3]
        axis = self.axes[0]
        if axis == "x":
            total_sum = quantity_callback(ryz, x, a, b, M)
        elif axis == "y":
            total_sum = quantity_callback(rxz, y, a, b, M)
        else:
            total_sum = quantity_callback(rxy, z, a, b, M)

        for id_mod, axis in enumerate(self.axes[1:]):
            a, b, M = self.models[id_mod*3:(id_mod+1)*3]
            axis = self.axes[id_mod]
            if axis == "x":
                total_sum += quantity_callback(ryz, x, a, b, M)
            elif axis == "y":
                total_sum += quantity_callback(rxz, y, a, b, M)
            else:
                total_sum += quantity_callback(rxy, z, a, b, M)
        return total_sum


    def evaluate_potential(self, x, y, z):
        """
        Returns the summed potential of all the disks at a specific point. xyz can be scalars or a vector
        """
        return self._evaluate_quantity(x, y, z, MMNModel.mn_potential)

    def evaluate_density(self, x, y, z):
        """
        Returns the summed density of all the disks at a specific point. xyz can be scalars or a vector
        """
        return self._evaluate_quantity(x, y, z, MMNModel.mn_density)

    def evaluate_forceR(self, x, y, z):
        """
        Returns the summed force of all the disks at a specific point. xyz can be scalars or a vector
        """
        return self._evaluate_quantity(x, y, z, MMNModel.mn_forceR)

    def evaluate_forceV(self, x, y, z):
        """
        Returns the summed force of all the disks at a specific point. xyz can be scalars or a vector
        """
        return self._evaluate_quantity(x, y, z, MMNModel.mn_forceV)

    def evaluate_circular_velocity(self, x, y, z):
        
        return self._evaluate_quantity(x, y, z, MMNModel.mn_circular_velocity)        

    def is_positive_definite(self):
        """
        This function returns true if the models are positive definite.
        """
        rm = op.fminbound(self.evaluate_density, 0, 1000)
        pm = self.evaluate_density(rm)
        print("rm=",rm)
        print("pm=",pm)
        return pm > 0.0

    

    

    