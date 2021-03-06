from tkinter import E
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

class SparsePro(nn.Module):
    def __init__(
        self,
        X,
        y,
        p=322,
        n=1299,
        k=9
    ):

        super(SparsePro, self).__init__()

        # data
        self.X = X
        self.y = y
        self.ytX = self.y.T @ self.X # compute once
        self.XtX = self.X.T @ self.X # compute once
        self.XX = self.XtX # TODO: fix this

        # hyper-parameters
        self.p = p # num SNPs
        self.n = n # num individuals
        self.k = k # max num of effects model accounts for
        self.y_var = torch.var(y) # phenotype variance
        self.b_var = 1 # TODO fix this
        self.h2 = 1 # TODO fix this

        # priors
        self.y_tau = torch.tensor(1.0 / (self.y_var * (1-self.h2)),
                        dtype=torch.float32)
        self.prior_pi = torch.ones((self.p,)) * (1/self.p)
        self.beta_prior_tau = torch.tile(torch.tensor(
                                1.0 / self.b_var * np.array([k+1 for k in range(self.k)]), 
                                dtype=torch.float32), (self.p, 1))
        self.beta_post_tau = torch.tile(XX.reshape(-1, 1), 
                                (1, self.k)) * self.y_tau + self.beta_prior_tau

        # latent variables
        self.softmax = nn.Softmax(dim=0)
        beta_mu, u = self.init_variational_params()
        self.u = nn.Parameter(u)
        self.beta_mu = nn.Parameter(beta_mu)

    def forward(self):
        ''' Compute the ELBO

        Returns
        -------
        elbo : tensor (1 x 1)
            divergence btwn variational approximation to the true posterior
        '''

        beta_all = (self.gamma() * self.beta_mu).sum(axis=1)
        ll1 = self.y_tau * torch.matmul(beta_all, self.ytX)
        ll2 = - 0.5 * self.y_tau * ((self.gamma() * 
            self.beta_mu**2).sum(axis=1) * self.XX).sum()
        W = self.gamma() * self.beta_mu
        WtRW = torch.matmul(torch.matmul(W.t(), self.XtX), W)
        ll3 = - 0.5 * self.y_tau * (WtRW.sum() - torch.diag(WtRW).sum())
        ll = ll1 + ll2 + ll3
        betaterm1 = -0.5 * (self.beta_prior_tau * self.gamma() 
            * (self.beta_mu**2)).sum()
        gammaterm1 = self.gamma() * torch.tile(
            self.prior_pi.reshape(-1, 1), (1, self.k))).sum()
        gammaterm2 = (self.gamma()[self.gamma() != 0] *
            torch.log(self.gamma()[self.gamma() != 0])).sum()
        mkl = betaterm1 + gammaterm1 - gammaterm2
        elbo = ll + mkl
        return elbo

    def gamma(self):
        ''' compute gamma as softmax(u)

        Because gamma must be a probability distribution, we 
        actually optimize over u then pass it through a softmax function to
        get gamma. This function thus allows easy access to gamma from u.

        Returns
        -------
        gamma : (p x k) tensor
            
        '''
        
        gamma = self.softmax(self.u)
        return gamma

    def init_variational_params(self):
        '''Initialize the variational parameters gamma and beta_mu with CAVI
        
        Initialize gamma and beta_mu with one iteration of CAVI, the 
        optimization procedure used in the original SparsePro paper. This is a
        good initialization because it breaks symmetry well, allowing for easier
        optimization. Because gamma must be a probability distribution, we 
        actually optimize over u then pass it through a softmax function to
        get gamma.

        Returns
        -------
        beta_mu : (p x k) tensor 
            initial value for variational parameter beta_mu
        u : (p x k) tensor
            initial value for variational parameter gamma = softmax(u)
        '''

        gamma = torch.zeros((self.p, self.k))
        beta_mu = torch.zeros((self.p, self.k))
        u = torch.zeros((self.p, self.k))

        for k in range(self.k):
            idxall = [x for x in range(self.k)]
            idxall.remove(k)
            beta_all_k = (gamma[:,idxall] * beta_mu[:,idxall]).sum(axis=1)
            beta_mu[:,k] = (self.ytX -torch.matmul(beta_all_k, self.XtX)) / (
                            self.beta_post_tau[:,k] * self.y_tau)
            u[:,k] = (-0.5*torch.log(self.beta_post_tau[:,k])
                        + torch.log(self.prior_pi.t()) 
                        + 0.5 * beta_mu[:,k]**2 * self.beta_post_tau[:,k])
            gamma[:,k] = self.softmax(u[:,k])
        return beta_mu, u