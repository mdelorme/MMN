import sys

import corner
import emcee
import matplotlib.pyplot as pl
import numpy as np
import scipy.optimize as op
from matplotlib.ticker import MaxNLocator

from model import MMNModel


class MMNFitter:
    """
    This class is used to fit a certain Multi Miyamoto Nagai model (with a predefined number of disks) to a datafile.
    """
    def __init__(self, n_walkers=100, n_steps=1000, random_seed=120, fit_type='potential', check_positive_definite=True, verbose=True):
        """
        Constructor for the MultiMiyamotoNagai fitter. The fitter is based on emcee.

        :param n_walkers: emcee parameter to indicate how many parallel walkers the MCMC will use to fit the data
        :param n_steps: How many steps should the MCMC method proceed before stopping
        :param random_seed: A seed used to generate the initial positions of the walkers
        """
        self.n_walkers = n_walkers
        self.n_steps = n_steps

        # The fitted models
        self.sampler = None
        self.samples = ()
        self.quantiles = None
        self.models = None
        self.axes = None
        self.ndim = 0
        self.fit_type = fit_type

        # The data samples we are fitting again :
        self.data = None
        self.n_values = 0
        self.yerr = None

        # Flags
        self.verbose = verbose
        self.check_DP = check_positive_definite

        np.random.seed(random_seed)

    def set_model_type(self, nx=0, ny=0, nz=1):
        """
        Defines the type of model we are trying to fit
        :param nx: Number of disks on the yz plane
        :param ny: Number of disks on the xz plane
        :param nz: Number of disks on the xy plane
        """
        self.ndim = (nx+ny+nz)*3
        self.models = np.random.rand(self.ndim)
        self.axes = ['x']*nx + ['y']*ny + ['z']*nz

    def load_data(self, filename):
        """
        Loads the data that needs to be fitted. The data should be in an ascii file with four columns : X Y Z potential
        :param filename: The filename to open
        """
        self.data = np.loadtxt(filename)
        self.n_values = self.data.shape[0]
        self.yerr = 0.01*np.random.rand(self.n_values)

    def sMN(self, models=(), fit_type=None):
        """
        Sums the values of the different Miyamoto on a set of points
        The type of value summed depends on the fit we want to realize
        :param models: the list of models we are summing. If none the models of the instance are taken
        :param fit_type: the type of fit we are doing. Can be "potential", "density", "force" or None. If None then
        the default fit_type of the instance is taken
        :return: a scalar, the total sum of all the models on all points
        """
        if len(models) == 0:
            models = self.models

        if not fit_type:
            fit_type = self.fit_type

        # We pick the function to apply according to the fit model
        if fit_type == 'density':
            eval_func = MMNModel.mn_density
        elif fit_type == 'potential':
            eval_func = MMNModel.mn_potential
        else:
            eval_func = MMNModel.mn_force

        # The positions of the points
        x = self.data[:, 0]
        y = self.data[:, 1]
        z = self.data[:, 2]

        # Radius on each plane
        rxy = np.sqrt(x**2+y**2)
        rxz = np.sqrt(x**2+z**2)
        ryz = np.sqrt(y**2+z**2)

        total_sum = 0.0

        # Summing on each model
        for id_mod, axis in enumerate(self.axes):
            a, b, M = models[id_mod*3:(id_mod+1)*3]
            if axis == "x":
                value = eval_func(ryz, x, a, b, M)
            elif axis == "y":
                value = eval_func(rxz, y, a, b, M)
            else:
                value = eval_func(rxy, z, a, b, M)

            total_sum += value
        return total_sum

    def loglikelihood(self, models):
        """
        This function computes the loglikelihood of the
        :param models: the list of models
        :return: the loglikelihood of the sum of models
        """

        M = MMNModel()
        
        # Checking that a+b > 0 for every model :
        for id_mod, axis in enumerate(self.axes):
            a, b, M = models[id_mod*3:(id_mod+1)*3]
            if a+b < 0:
                return -np.inf

            # If we are checking for positive-definiteness we add the disk to the model
            if self.check_DP:
                M.add_model(axis, a, b, M)

        # Now checking for positive-definiteness:
        if self.check_DP:
            if not M.is_positive_definite():
                return -np.inf

        # Everything ok, we proceed with the likelihood :
        p = self.data[:, 3]
        model = self.sMN(models)
        inv_sigma2 = 1.0/(self.yerr**2)
        return -0.5*(np.sum((p-model)**2*inv_sigma2-np.log(inv_sigma2)))

    def maximum_likelihood(self):
        """
        Computation of the maximum of likelihood of the models
        """
        if self.verbose:
            print("Computing maximum of likelihood")

        # Optimizing the parameters of the models to minimize the loglikelihood
        models = self.models
        chi2 = lambda m: -2 * self.loglikelihood(m)
        result = op.minimize(chi2, models)
        values = result["x"]

        if self.verbose:
            print("Maximum of likelihood results :")

            axis_stat = {"x": [1, "yz"], "y": [1, "xz"], "z": [1, "xy"]}
            for id_mod, axis in enumerate(self.axes):
                stat = axis_stat[axis]
                axis_name = "{0}{1}".format(stat[1], stat[0])

                print("a{0} = {1} (initial : {2})".format(axis_name, values[id_mod*3], models[id_mod*3]))
                print("b{0} = {1} (initial : {2})".format(axis_name, values[id_mod*3+1], models[id_mod*3+1]))
                print("M{0} = {1} (initial : {2})".format(axis_name, values[id_mod*3+2], models[id_mod*3+2]))

                stat[0] += 1

        # Storing the best values as current models
        self.models = values

    def fit_data(self, burnin=100):
        """
        This function finds the parameters of the models using emcee
        :param burnin: the number of timesteps to keep after running emcee
        :returns: A list of all the samples truncated to give only from the burning timestep
        """

        # We initialize the positions of the walkers by adding a small random component to each parameter
        pos = [self.models + 1e-4*np.random.randn(self.ndim) for i in range(self.n_walkers)]

        # Running the MCMC to get the parameters
        if self.verbose:
            print("Running emcee ...")

        self.sampler = emcee.EnsembleSampler(self.n_walkers, self.ndim, self.loglikelihood)
        self.sampler.run_mcmc(pos, self.n_steps, rstate0=np.random.get_state())

        # Storing the last burnin results
        nstp= 0.5*self.n_steps
        self.samples = self.sampler.chain[:, nstp:, :].reshape((-1, self.ndim))

        if self.verbose:
            print("Done.")

        return self.samples

    def plot_disk_walkers(self, id_mod):
        """
        Plotting the walkers on each parameter of a certain model
        :param id_mod: the id of the disk parameters you want to plot
        """
        axis_name = {"x": "yz", "y": "xz", "z": "xy"}[self.axes[id_mod]]
        fig, axes = pl.subplots(3, 1, sharex=True, figsize=(8, 9))
        axes[0].plot(self.sampler.chain[:, :, 0].T, color="k", alpha=0.4)
        axes[0].yaxis.set_major_locator(MaxNLocator(5))
        axes[0].axhline(self.models[id_mod*3], color="#888888", lw=2)
        axes[0].set_ylabel("$a{0}$".format(axis_name))

        axes[1].plot(self.sampler.chain[:, :, 1].T, color="k", alpha=0.4)
        axes[1].yaxis.set_major_locator(MaxNLocator(5))
        axes[1].axhline(self.models[id_mod*3+1], color="#888888", lw=2)
        axes[1].set_ylabel("$b{0}$".format(axis_name))

        axes[2].plot(self.sampler.chain[:, :, 2].T, color="k", alpha=0.4)
        axes[2].yaxis.set_major_locator(MaxNLocator(5))
        axes[2].axhline(self.models[id_mod*3+2], color="#888888", lw=2)
        axes[2].set_ylabel("$M{0}$".format(axis_name))
        fig.savefig("Time.png")

    def corner_plot(self):
        """
        Draws the corner plot of the fitted data
        """
        labels = []
        axis_stat = {"x": [1, "yz"], "y": [1, "xz"], "z": [1, "xy"]}

        for id_mod, axis in enumerate(self.axes):
            stat = axis_stat[axis]
            axis_name = "{0}{1}".format(stat[1], stat[0])
            labels += ["a{0}".format(axis_name), "b{0}".format(axis_name), "M{0}".format(axis_name)]
            stat[0] += 1

        if self.verbose:
            print("Computing corner plot ...")

        figt = corner.corner(self.samples, labels=labels, truths=self.models)
        figt.savefig("Triangle.png")

    def compute_quantiles(self, quantiles=(16, 50, 84)):
        """
        Finds the quantiles values on the whole sample kept after emcee run. The results are stored in the quantiles
        attribute of the class.
        :param quantiles: a tuple indicating what quantiles are to be computed
        """
        if len(quantiles) != 3:
            sys.stderr.write('Warning : The quantile list should always be a triplet')
            return

        if len(self.samples) == 0:
            sys.stderr.write('Warning : You should not run compute_quantiles before fit_data ! Trying to compute quantiles.')

        k = lambda v: (v[1], v[2]-v[1], v[1]-v[0])
        qarray = np.array(np.percentile(self.samples, quantiles, axis=0))
        self.quantiles = np.array((qarray[1], qarray[2]-qarray[1], qarray[1]-qarray[0])).T

        if self.verbose:
            print("MCMC results :")
            axis_stat = {"x": [1, "yz"], "y": [1, "xz"], "z": [1, "xy"]}
            for id_mod, axis in enumerate(self.axes):
                stat = axis_stat[axis]
                axis_name = "{0}{1}".format(stat[1], stat[0])
                base_format = "{0} = {1[0]} +: {1[1]} -: {1[2]}"
                print("a"+base_format.format(axis_name, self.quantiles[id_mod*3], self.quantiles[id_mod*3]))
                print("b"+base_format.format(axis_name, self.quantiles[id_mod*3+1], self.quantiles[id_mod*3+1]))
                print("M"+base_format.format(axis_name, self.quantiles[id_mod*3+2], self.quantiles[id_mod*3+2]))
                stat[0] += 1

        return self.quantiles


