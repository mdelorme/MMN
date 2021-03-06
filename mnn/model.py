from __future__ import print_function
import scipy.optimize as op
import numpy as np
import warnings

# Helper
is_array = lambda x: isinstance(x, np.ndarray)

class MNnError(Exception):
    """ 
    Miyamoto-Nagai negative exceptions : raised when the models parameters are in invalid ranges or that the user is doing something he should not
    """
    def __init__(self, msg):
        self.msg = msg
        
    def __str__(self):
        return self.msg


#G=4.302e-3
G = 0.0043008211
"""float: Gravitational constant to use when evaluating potential or forces on the models. 
The value must be changed to match the units required by the user."""

class MNnModel(object):
    """
    Miyamoto-Nagai negative model.
    This object is a potential-density pair expansion : it consists of a sum of Miyamoto-Nagai dics allowing 
    """
    def __init__(self, diz=1.0):
        """ Constructor for the summed Miyamoto-Nagai-negative model

        Args:
            diz (float): Normalization factor applied to all the discs (default = 1.0)
        """
        # The discs and fit description
        self.discs = []
        self.axes = []
        self.diz = diz

        # The data the model is fitting
        self.data = None
        self.yerr = None
        self.n_values = 0

    def load_from_array(self, model, axes):
        """ Generates the model from a numpy array
        
        Args:
           model (Numpy array): A Nx3 numpy array holding the model.
           axes (tuple): A tuple indicating along which axis each disc is aligned
        """
        for m, ax in zip(model, axes):
            a, b, M = m
            self.add_disc(ax, a, b, M)

    def add_disc(self, axis, a, b, M):
        """ Adds a Miyamoto-Nagai negative disc to the model, this disc will be included in the summation process when evaluating quantities with the model.

        A disc is a list of three parameters *a*, *b* and *M*. All the parameters of the discs are stored in a flat list with no real separation. 
        This is done so that emcee can be fed the array directly without any transformation.

        The model accounts for negative values of ``a``. The constraints on the parameters are the following :

          * ``b >= 0``
          * ``M >= 0``
          * ``a+b >= 0``

        Args:
            axis ({'x', 'y', 'z'}): the normal axis of the plane for the disc.
            a (float): disc scale
            b (float): disc height
            M (float): disc mass

        Raises:
            :class:`mnn.model.MNnError` : if one of the constraints if not satisfied

        Example:
            Adding a disc lying on the xy plane will be done as follows:

            >>> m = MNnModel()
            >>> m.add_disc('z', 1.0, 0.1, 10.0)
        """
        if b<0:
            raise MNnError('The height of a disc cannot be negative (b={0})'.format(b))
        #elif M<0:
        #    raise MNnError('The mass of a disc cannot be negative (M={0})'.format(M))
        elif a+b<0:
            print('Warning : The sum of the scale and height of the disc is negative (a={0}, b={1})'.format(a,b)) 

        self.discs += [a, b, M]
        self.axes.append(axis)

    def add_discs(self, values):
        """ Wrapper for the :func:`~mnn.model.MNnModel.add_disc` method to add multiple MNn discs at the same time.
        
        Args:
            values (list of 4-tuples): The parameters of the discs to add. One 4-tuple corresponds to one disc.

        Raises:
            :class:`mnn.model.MNnError` : if one of the constraints if not satisfied

        Example:
            Adding one disc on the xy place with parameters (1.0, 0.1, 50.0) and one disc on the yz plane with parameters (1.0, 0.5, 10.0) 
            will be done as follows:

            >>> m = MNnModel()
            >>> m.add_discs([('z', 1.0, 0.1, 50.0), ('x', 1.0, 0.5, 10.0)])
        """
        for axis, a, b, M in values:
            self.add_disc(axis, a, b, M)

    def get_model(self):
        """ Copies the discs currently stored and returns them as a list of 4-tuples [(axis1, a1, b1, M1), (axis2, a2, b2, ...), ... ]
        
        Returns:
            A list of 4-tuples (axis, a, b, M).

        Example:
            >>> m = MNnModel()
            >>> m.add_discs([('z', 1.0, 0.1, 50.0), ('x', 1.0, 0.5, 10.0)])
            >>> m.get_model()
            [('z', 1.0, 0.1, 50.0), ('x', 1.0, 0.5, 10.0)]
        """
        res = []
        for id_axis, axis in enumerate(self.axes):
            res += [tuple([axis] + self.discs[id_axis*3:(id_axis+1)*3])]
        return res

    @staticmethod
    def callback_from_string(quantity):
        """ Returns the static function callback associated to a given quantity string.

        Returns:
            A function callback : One of the following : :func:`~mnn.model.MNnModel.mn_density`, :func:`~mnn.model.MNnModel.mn_potential`, :func:`~mnn.model.MNnModel.mn_force`
        """
        cb_from_str = {'density' : MNnModel.mn_density,
                       'potential' : MNnModel.mn_potential,
                       'force' : MNnModel.mn_force}

        if not quantity in cb_from_str.keys():
            return MMnModel.mn_density

        return cb_from_str[quantity]

    @staticmethod
    def get_tangent_coordinates(x, y, z, axis):
        """ Returns the tangent and normal coordinates used in :func:`~mnn.model.MNnModel.mn_force` from a set of cartesian coordinates and an axis.
        The correspondence between axis and tangent coordinates are the following : 

        +------+----+----+---+
        | axis | t1 | t2 | n |
        +======+====+====+===+
        | x    | y  | z  | x |
        +------+----+----+---+
        | y    | x  | z  | y |
        +------+----+----+---+
        | z    | x  | y  | z |
        +------+----+----+---+

        Args:
            x (float or numpy-array): x coordinate of the points to convert
            y (float or numpy-array): y coordinate of the points to convert
            z (float or numpy-array): z coordinate of the points to convert
            axis ({'x', 'y', 'z'}): the normal axis of the disc

        
        Returns:
            A tuple containing three coordinates :

            - **t1** (float or numpy-array): The first tangential coordinate for a disc aligned on ``axis``
            - **t2** (float or numpy-array): The second tangential coordinate for a disc aligned on ``axis``
            - **n** (float or numpy-array): The normal component for a disc aligned on ``axis``
        """

        if axis == 'x':
            return y, z, x
        elif axis == 'y':
            return x, z, y
        else:
            return x, y, z

    @staticmethod
    def mn_density(r, z, a, b, M):
        """ Evaluates the density of a single Miyamoto-Nagai negative disc (a, b, M) at polar coordinates (r, z).

        Args:
            r (float): radius of the point where the density is evaluated
            z (float): height of the point where the density is evaluated
            a (float): disc scale
            b (float): disc height
            M (float): disc mass

        Returns:
            *float* : the density (scaled to the model) at (r, z)

        Note:
            This method does **not** check the validity of the constraints ``b>=0``, ``M>=0``, ``a+b>=0``
        """
        h = np.sqrt((z**2.0)+(b**2.0))
        fac = (b**2)*M/(4.0*np.pi)
        ah2 = (a+h)**2.0
        ar2 = a*(r**2.0)
        a3h = a+3.0*h
        num = ar2+(a3h*ah2)
        den = (h**3.0)*((r**2)+ah2)**2.5
        return fac*num/den

    @staticmethod
    def mn_potential(r, z, a, b, M):
        """ Evaluates the potential of a single Miyamoto-Nagai negative disc (a, b, M) at polar coordinates (r, z).

        Args:
            r (float): radius of the point where the density is evaluated
            z (float): height of the point where the density is evaluated
            a (float): disc scale
            b (float): disc height
            Mo (float): disc mass

        Returns:
            *float* : the potential (scaled to the model) at (r, z)

        Note:
            This method does **not** check the validity of the constraints ``b>=0``, ``M>=0``, ``a+b>=0``

        Note:
            This method relies on user-specified value for the gravitational constant. 
            This value can be overriden by setting the value :data:`mnn.model.G`.
        """
        #M1 = np.abs(M)
        M1 = M
        h = np.sqrt(z**2 + b**2)
        den = r**2 + (a + h)**2
        return -G*M1 / np.sqrt(den)

    @staticmethod
    def mn_force(t1, t2, n, a, b, M, axis):
        """ Evaluates the force of a single Miyamoto-Nagai negative disc (a, b, M) at a set of tangent/radial coordinates.

        Args:
            t1 (float): first tangent coordinate of the point where the density is evaluated
            t2 (float): second tangent coordinate of the point where the density is evaluated
            n (float): height of the point where the density is evaluated
            a (float): disc scale
            b (float): disc height
            Mo (float): disc mass
            axis ({'x', 'y', 'z'}): the normal axis of the disc
        
        Returns:
           *numpy array* : the force applied at point (r, z) relative to the disc in cartesian coordinates.

        Note:
            This method does **not** check the validity of the constraints ``b>=0``, ``M>=0``, ``a+b>=0``

        Note:
            This method relies on user-specified value for the gravitational constant. 
            This value can be overriden by setting the value :data:`mnn.model.G`.

        Note: 
            The tangent coordinates allow us to abstract the orientation of the disc to sum everything up for the model.
            Although it might seem a bit heavy here, it is done to simplify the summation process for the model. Since
            we require a vector as output we can't use anymore the "simple" cylindrical coordinates.

            The correspondence between axis and tangent coordinates are given in the definition of :func:`~mnn.model.MNnModel.get_tangent_coordinates`

            
        """
        num = -G * M
        R2 = t1**2 + t2**2
        f1 = np.sqrt(b**2 + n**2)
        f2 = (a + f1)**2
        den = (R2 + f2)**1.5
        q1 = num / den
        f3 = np.sqrt(n**2 + b**2)
        q2 = (a + f3) / f3

        # Checking dimension consistency between operands
        at1 = is_array(t1)
        at2 = is_array(t2)
        at3 = is_array(n)
        
        if any((at1, at2, at3)):
            if at1:
                Nv = t1.shape[0]
            elif at2:
                Nv = t2.shape[0]
            else:
                Nv = n.shape[0]
            
            if not at1:
                t1 = np.asarray([t1]*Nv)
            if not at2:
                t2 = np.asarray([t2]*Nv)
            if not at3:
                n = np.asarray([n]*Nv)

        # Ordering the result according to the axis so that the coordinates of the disc transforms
        # correctly into cartesian coordinates.
        if axis == 'x':
            res = q1 * np.asarray((n*q2, t1, t2))
        elif axis == 'y':
            res = q1 * np.asarray((t1, n*q2, t2))
        else:
            res = q1 * np.asarray((t1, t2, n*q2))

        return res.T
        

    # Point evaluation
    def evaluate_potential(self, x, y, z):
        """ Evaluates the summed potential over all discs at specific positions 
        
        Args:
            x, y, z (float or Nx1 numpy array): Cartesian coordinates of the point(s) to evaluate
           
        Returns:
            The summed potential over all discs at position ``(x, y, z)``.

        Note:
            If ``x``, ``y`` and ``z`` are numpy arrays, then the return value is a Nx1 value of the potential evaluated 
            at every point ``(x[i], y[i], z[i])``
        """
        return self._evaluate_scalar_quantity(x, y, z, MNnModel.mn_potential)

    
    def evaluate_density(self, x, y, z):
        """ Evaluates the summed density over all discs at specific positions 
        
        Args:
            x, y, z (float or Nx1 numpy array): Cartesian coordinates of the point(s) to evaluate
           
        Returns:
            The summed density over all discs at position ``(x, y, z)``.

        Note:
            If ``x``, ``y`` and ``z`` are numpy arrays, then the return value is a Nx1 vector of the evaluated potential 
            at every point ``(x[i], y[i], z[i])``
        """
        return self._evaluate_scalar_quantity(x, y, z, MNnModel.mn_density)

    def evaluate_force(self, x, y, z):
        """ Evaluates the summed force over all discs at specific positions 
        
        Args:
            x, y, z (float or Nx1 numpy array): Cartesian coordinates of the point(s) to evaluate
           
        Returns:
            The summed force over all discs at position ``(x, y, z)``.

        Note:
            If ``x``, ``y`` and ``z`` are numpy arrays, then the return value is a Nx3 vector of the evaluated potential 
            at every point ``(x[i], y[i], z[i])``
        """

        # This is not relying on evaluate_scalar_quantity since the result is a vector and the function signature is not
        # exactly the same. It is therefore better to have a separate definition instead of adding exceptional cases in the
        # evaluate_scalar_quantity method.

        # Storing the first value directly as the output variable.
        # This allows us to avoid testing for scalar or vector
        # while initializing the total_sum variable
        a, b, M = self.discs[0:3]
        axis = self.axes[0]
        t1, t2, n = self.get_tangent_coordinates(x, y, z, axis)
        total_sum = self.mn_force(t1, t2, n, a, b, M, axis)

        id_mod = 1
        for axis in self.axes[1:]:
            a, b, M = self.discs[id_mod*3:(id_mod+1)*3]
            t1, t2, n = self.get_tangent_coordinates(x, y, z, axis)
            total_sum += self.mn_force(t1, t2, n, a, b, M, axis)
            id_mod += 1
            
        return total_sum

    # Vector eval
    def evaluate_density_vec(self, x):
        """ Returns the summed density of all the discs at specific points.

        Args:
            x (Nx3 numpy array): Cartesian coordinates of the point(s) to evaluate
           
        Returns:
            The summed density over all discs at every position in vector ``x``.
        """
        return self._evaluate_scalar_quantity(x[:,0], x[:,1], x[:,2], MNnModel.mn_density)
    
    def evaluate_potential_vec(self, x):
        """ Returns the summed potential of all the discs at specific points.

        Args:
            x (Nx3 numpy array): Cartesian coordinates of the point(s) to evaluate
           
        Returns:
            The summed potential over all discs at every position in vector ``x``.
        """
        return self._evaluate_scalar_quantity(x[:,0], x[:,1], x[:,2], MNnModel.mn_potential)

    def evaluate_force_vec(self, x):
        """ Returns the summed force of all the discs at specific points.

        Args:
            x (Nx3 numpy array): Cartesian coordinates of the point(s) to evaluate
           
        Returns:
            The summed force over all discs at every position in vector ``x``.
        """
        return self.evaluate_force(x[:,0], x[:,1], x[:,2])
    

    def is_positive_definite(self, max_range=None):
        """ Returns true if the sum of the discs are positive definite.
        
        The methods tests along every axis if the minimum of density is positive. If it is not the case then the model should 
        NOT be used since we cannot ensure positive density everywhere.

        Args:
            max_range (a float or None): Maximum range to evaluate, if None the maximum scale radius will be taken. (default = None)

        Returns:
            A boolean indicating if the model is positive definite.
        """
        mods = self.get_model()
        
        for axis in ['x', 'y', 'z']:
            if max_range == None:
                # Determine the interval
                mr = 0.0
                for m in mods:
                    # Relevant value : scale parameter for the parallel axes
                    if m[0] != axis:
                        if m[1] > mr:
                            mr = m[1]

                # If we don't have a max_range then we can skip this root finding : the function cannot go below zero
                if abs(mr) < 1e-18:
                    continue

                mr *= 10.0 # Multiply by a factor to be certain "everything is enclosed"
            else:
                mr = max_range

            xopt, fval, ierr, nf = op.fminbound(self._evaluate_density_axis, 0.0, max_range, args = [axis], disp=0, full_output=True)
            if fval < 0.0:
                #print('Warning : This model has a root along the {0} axis (r={1}) : density can go below zero'.format(axis, x0))
                return False

        return True

    def generate_dataset_meshgrid(self, xmin, xmax, nx, quantity='density'):
        """ Generates a numpy meshgrid of data from the model
        
        Args:
            xmin (3-tuple of floats): The low bound of the box
            xmax (3-tuple of floats): The high bound of the box
            nx (3-tuple of floats): Number of points in every direction
            quantity ({'density', 'potential', 'force'}) : Type of quantity to fill the box with (default='density')

        Returns:
            A 4-tuple containing

            - **vx, vy, vz** (*N vector of floats*): The x, y and z coordinates of each point of the mesh
            - **res** (*N vector of floats*): The values of the summed quantity over all discs at each point of the mesh
        Raises:
            MemoryError: If the array is too big
            :class:`mnn.model.MNnError`: If the quantity parameter does not correspond to anything known
        """
        quantity_vec = ('density', 'potential', 'force')
        if quantity not in quantity_vec:
            print('Error : Unknown quantity type {0}, possible values are {1}'.format(quantity, quantity_vec))
            return

        if len(xmin) != 3 or len(xmax) != 3 or len(nx) != 3:
            print('Error : You must provide xmin, xmax and nx as triplets of floats')
            return

        Xsp = []
        for i in range(3):
            Xsp.append(np.linspace(xmin[i], xmax[i], nx[i]))

        gx, gy, gz = np.meshgrid(Xsp[0], Xsp[1], Xsp[2], indexing='ij')

        if quantity == 'density':
            res = self.evaluate_density(gx, gy, gz)
        elif quantity == 'potential':
            res = self.evaluate_potential(gx, gy, gz)
        elif quantity == 'force':
            res = self.evaluate_force(gx, gy, gz)
        else:
            raise MNnError('Quantity {0} unknown. Cannot fill grid mesh.'.format(quantity))
            
        return gx, gy, gz, res

    
    # Axis evaluation, non-documented. Should not be used apart from the is_positive_definite method ! 
    def _evaluate_density_axis(self, r, axis):
        if axis == 'x':
            return self._evaluate_scalar_quantity(r, 0, 0, MNnModel.mn_density)
        if axis == 'y':
            return self._evaluate_scalar_quantity(0, r, 0, MNnModel.mn_density)
        else:
            return self._evaluate_scalar_quantity(0, 0, r, MNnModel.mn_density)

    def _evaluate_scalar_quantity(self, x, y, z, quantity_callback):
        """ Generic private function to evaluate a quantity on the summed discs at a specific point of space.
        this function is private and should be only used indirectly via one of the following 
        :func:`~mnn.model.MNnModel.evaluate_density`, :func:`~mnn.model.MNnModel.evaluate_potential`, 
        :func:`~mnn.model.MNnModel.evaluate_density_vec`, :func:`~mnn.model.MNnModel.evaluate_potential_vec`

        Args:
            x, y, z (floats or Nx1 numpy arrays): Cartesian coordinates of the point(s) to evaluate
            quantity_callback (function callback): a callback indicating which function is used to evaluate the quantity

        Returns:
            *float* or *Nx1 numpy array* : The quantities evaluated at each points given in entry

        Note:
            If ``x``, ``y`` and ``z`` are numpy arrays, then the method evaluates the quantity over every point (x[i], y[i], z[i])
        """
        # Radius on each plane
        rxy = np.sqrt(x**2+y**2)
        rxz = np.sqrt(x**2+z**2)
        ryz = np.sqrt(y**2+z**2)

        # Storing the first value directly as the output variable.
        # This allows us to avoid testing for scalar or vector
        # while initializing the total_sum variable
        a, b, M = self.discs[0:3]
        axis = self.axes[0] 
        if axis == "x":
            total_sum = quantity_callback(ryz, x, a, b, M)
        elif axis == "y":
            total_sum = quantity_callback(rxz, y, a, b, M)
        else:
            total_sum = quantity_callback(rxy, z, a, b, M)

        id_mod = 1
        for axis in self.axes[1:]:
            a, b, M = self.discs[id_mod*3:(id_mod+1)*3]
            if axis == "x":
                total_sum += quantity_callback(ryz, x, a, b, M)
            elif axis == "y":
                total_sum += quantity_callback(rxz, y, a, b, M)
            else:
                total_sum += quantity_callback(rxy, z, a, b, M)
            id_mod += 1
            
        return total_sum
        
    
    

    

    
