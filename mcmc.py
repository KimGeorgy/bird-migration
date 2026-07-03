import numpy as np
from scipy.special import gammaln


def LogLikelihood(y_t, z_t, x_t, p_t, w_t):
    mask = (z_t == 1) & (x_t > 0)
    print(np.where(mask, y_t, 0).sum())

    logL = np.sum( np.log(p_t ** (1 - z_t)) )
    print(logL)
    logL += np.sum( np.log((1 - p_t)**z_t) )
    print(logL)
    #logL += - np.log(1 - np.prod(p_t)) # too small, taylor
    logL += np.prod(p_t)
    print(logL)
    logL += gammaln( np.sum(np.where(mask, x_t * w_t, 0)) )
    print(logL)
    safe_gammaln_xt_wt = np.where(mask, gammaln(np.where(mask, x_t * w_t, 1)), 0)
    logL += -np.sum(safe_gammaln_xt_wt)
    print(logL)
    safe_log_yt = np.where(mask, np.log(np.where(mask, y_t, 1)), 0)
    logL += np.sum( np.where(mask, (x_t * w_t - 1) * safe_log_yt, 0) )
    # is it better to leave the deg outside or inside
    return logL