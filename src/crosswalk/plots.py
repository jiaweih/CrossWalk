import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import crosswalk as cw


def dose_response_curve(dose_variable, obs_method,
                        continuous_variables=[], 
                        cwdir=None, cwdata=None, cwmodel=None,
                        file_name='dose_response_plot',
                        from_zero=False, include_bias=False,
                        ylim=None, plot_note=None, write_file=False):
    """Dose response curve.
    Args:
        dose_variable (str):
            Dose variable name.
        obs_method (str):
            Alternative definition or method intended to be plotted.
        continuous_variables (list):
            List of continuous covariate names.
        cwdir (str):
            Directory where to save the plot.
        cwdata (CWData object):
            CrossWalk data object.
        cwmodel (CWModel object):
            Fitted CrossWalk model object.
        from_zero (bool):
            If set to be True, y-axis will start from zero.
        ylim (list of int or float):
            y-axis bound. E.g. [0, 10]
        file_name (str):
            File name for the plot.
        plot_note (str):
            The notes intended to be written on the title.
        include_bias (bool):
            Whether to include bias or not.
        write_file (bool):
            Specify `True` if the plot is expected to be saved on disk.
            If True, `cwdir` should be specified too.

    """ 
    data_df = pd.DataFrame({'y': cwdata.df[cwdata.col_obs].values, 
                            'se': cwdata.df[cwdata.col_obs_se].values, 
                            'w': cwmodel.lt.w, f"{dose_variable}": cwdata.df[dose_variable], 
                            "obs_method": np.ravel(cwdata.alt_dorms), 
                            "dorm_alt": cwdata.df[cwdata.col_alt_dorms].values, 
                            "dorm_ref": cwdata.df[cwdata.col_ref_dorms].values})
    
    # drop dose variable
    continuous_variables = [v for v in continuous_variables if v != dose_variable]
    cov_idx = {} # dictionary of cov_model name with corresponding index
    lst_intervals = [] # list of cov_model with correponding number of intervals
    for idx in np.arange(len(cwmodel.cov_models)):
        cov = cwmodel.cov_models[idx].cov_name
        cov_idx[cov] = idx
        if cwmodel.cov_models[idx].spline:
            num_intervals = cwmodel.cov_models[idx].spline.num_intervals
        else:
            # For cov with no spline
            num_intervals = 1
        lst_intervals.append(num_intervals)
    # Slices for each cov based on number of knots; for extracting betas later on
    # lst_slices = cw.utils.sizes_to_slices(np.array(lst_intervals))
    lst_slices = sizes_to_slices(np.array(lst_intervals))
    
    # check for knots
    if dose_variable in cwdata.covs.columns:
        idx = cov_idx[dose_variable]
        if cwmodel.cov_models[idx].spline:
            knots = cwmodel.cov_models[idx].spline.knots
        else:
            knots = np.array([])
    else:
        knots = np.array([])

    # determine minimum and maximum exposure
    if knots.any():
        min_cov = knots[0]
        max_cov = knots[-1]
    else:
        min_cov = np.min(data_df[dose_variable])
        max_cov = np.max(data_df[dose_variable])
        
    if from_zero:
        min_cov = 0

    # construct dataframe for prediction
    cov_range = (max_cov - min_cov)
    dose_grid = np.arange(min_cov, max_cov + cov_range * 0.01, cov_range / 100)

    cols = cwdata.covs.columns
    if include_bias:
        pred_df = pd.DataFrame(dict(zip(cols, np.ones(len(cols)))),
            index=np.arange(len(dose_grid)))
    else:
        pred_df = pd.DataFrame(dict(zip(cols, np.zeros(len(cols)))),
            index=np.arange(len(dose_grid)))
        pred_df['intercept'] = 1
        
    # if it's continuous variable, take median 
    for var in continuous_variables:
        pred_df[var] = np.median(cwdata.get_covs(var))

    # predict for line
    pred_df[dose_variable] = dose_grid
    pred_df['obs_method'] = obs_method
    # prev and prev_se values don't matter (0-1)
    pred_df['prev'] = 0.1
    pred_df['prev_se'] = 0.1
    y_pred = cwmodel.adjust_orig_vals(       
          df=pred_df,            
          orig_dorms = "obs_method", 
          orig_vals_mean = "prev",  
          orig_vals_se = "prev_se"
        )
    y_mean = y_pred['pred_diff_mean']
    y_sd_fixed = y_pred['pred_diff_sd']
    # Standard deviation for effects including heterogeneity
    y_sd = np.sqrt(y_sd_fixed**2 + cwmodel.gamma)

    # lower/upper bound with fixed effect and heterogeneity
    y_lo, y_hi = y_mean - 1.96*y_sd, y_mean + 1.96*y_sd
    # lower/upper bound with only fixed effect
    y_lo_fe, y_hi_fe = y_mean - 1.96*y_sd_fixed, y_mean + 1.96*y_sd_fixed

     # predict for cwdata
    data_df['intercept'] = 1
    data_df['prev'] = 0.1
    data_df['prev_se'] = 0.1
    data_pred = cwmodel.adjust_orig_vals(       
          df=data_df,            
          orig_dorms = "obs_method", 
          orig_vals_mean = "prev",  
          orig_vals_se = "prev_se"
        )
    # data_pred = data_pred['pred_diff_mean']
    data_df['pred'] = data_pred['pred_diff_mean']

    # determine points inside/outside funnel
    data_df['position'] = 'inside funnel'
    data_df.loc[data_df.y < (data_df.pred - (data_df.se * 1.96)).values,
                'position'] = 'outside funnel'
    data_df.loc[data_df.y > (data_df.pred + (data_df.se * 1.96)).values,
                'position'] = 'outside funnel'

    # get inlier/outlier 
    data_df.loc[data_df.w >= 0.6, 'trim'] = 'inlier'
    data_df.loc[data_df.w < 0.6, 'trim'] = 'outlier'

    # get plot guide
    data_df['plot_guide'] = data_df['trim'] + ', ' + data_df['position']
    plot_key = {
        'inlier, inside funnel':('o', 'seagreen', 'darkgreen'),
        'inlier, outside funnel':('o', 'coral', 'firebrick'),
        'outlier, inside funnel':('x', 'darkgreen', 'darkgreen'),
        'outlier, outside funnel':('x', 'firebrick', 'firebrick')
    }
    
    # get scaled marker size
    data_df['size_var'] = 1 / data_df.se
    data_df['size_var'] = data_df['size_var'] * (300 / data_df['size_var'].max())
    
    # plot
    sns.set_style("whitegrid")
    plt.figure(figsize=(10, 8))
    plt.rcParams['axes.edgecolor'] = '0.15'
    plt.rcParams['axes.linewidth'] = 0.5
    plt.fill_between(pred_df[dose_variable], y_lo, y_hi, 
        alpha=0.5, color='lightgrey')
    plt.fill_between(pred_df[dose_variable], y_lo_fe, y_hi_fe, 
        alpha=0.75, color='darkgrey')
    plt.plot(pred_df[dose_variable], y_mean, color='black', linewidth=0.75)
    plt.xlim([min_cov, max_cov])
    if ylim is not None:
        plt.ylim(ylim)
    plt.xlabel('Exposure', fontsize=10)
    plt.xticks(fontsize=10)
    plt.ylabel('Effect size', fontsize=10)
    plt.yticks(fontsize=10)

    # other comparison
    non_direct_df = data_df.loc[
    (data_df.dorm_ref != cwmodel.gold_dorm) | (data_df.dorm_alt != obs_method)
    ]
    # direct comparison
    plot_data_df = data_df.loc[
    (data_df.dorm_ref == cwmodel.gold_dorm) & (data_df.dorm_alt == obs_method)
    ]
    
    for key, value in plot_key.items():
        plt.scatter(
            plot_data_df.loc[plot_data_df.plot_guide == key, f'{dose_variable}'],
            plot_data_df.loc[plot_data_df.plot_guide == key, 'y'],
            s=plot_data_df.loc[plot_data_df.plot_guide == key, 'size_var'],
            marker=value[0], facecolors=value[1], edgecolors=value[2], 
            linewidth=0.6, alpha=.6, label=key
        )
    plt.scatter(non_direct_df[f'{dose_variable}'], non_direct_df['y'],
                facecolors='grey', edgecolors='grey', alpha=.3,
                s=non_direct_df.loc[non_direct_df.plot_guide == key, 'size_var'])
    # Content string with betas
    betas = list(np.round(cwmodel.fixed_vars[obs_method], 3))
    content_string = ""
    for idx in np.arange(len(cwmodel.cov_models)):
        cov = cwmodel.cov_models[idx].cov_name
        knots_slices = lst_slices[idx]
        content_string += f"{cov}: {betas[knots_slices]}; "
    # Plot title
    if plot_note is not None:
        plt.title(content_string, fontsize=10)
        plt.suptitle(plot_note, y=1.01, fontsize=12)
    else:
        plt.title(content_string, fontsize=10)
    plt.legend(loc='upper left')
    
    for knot in knots:
        plt.axvline(knot, color='navy', linestyle='--', alpha=0.5, linewidth=0.75)
    # Save plots
    if write_file:
        assert cwdir is not None, "cwdir is not specified!"
        outfile = os.path.join(cwdir, f'{file_name}.pdf')
        plt.savefig(outfile, orientation='landscape', bbox_inches='tight')
        print(f"Dose response plot saved at {outfile}")
    else:
        plt.show()


def funnel_plot(obs_method='Self-reported', cwdata=None, cwmodel=None, 
                continuous_variables=[], cwdir=None, file_name='funnel_plot', 
                plot_note=None, include_bias=False, write_file=False):
    """Funnel Plot.
    Args:
        obs_method (str):
            Alternative definition or method intended to be plotted.
        cwdata (CWData object):
            CrossWalk data object.
        cwmodel (CWModel object):
            Fitted CrossWalk model object.
        continuous_variables (list):
            List of continuous covariate names.
        cwdir (str):
            Directory where to save the plot.
        file_name (str):
            File name for the plot.
        plot_note (str):
            The notes intended to be written on the title.
        include_bias (bool):
            Whether to include bias or not.
        write_file (bool):
            Specify `True` if the plot is expected to be saved on disk.
            If True, `cwdir` should be specified too.

    """
    assert obs_method in np.unique(cwdata.alt_dorms), f"{obs_method} not in alt_dorms!"

    data_df = pd.DataFrame({'y': cwdata.obs, 'se': cwdata.obs_se, 'w': cwmodel.lt.w,
                            "dorm_alt": cwdata.df[cwdata.col_alt_dorms].values, 
                            "dorm_ref": cwdata.df[cwdata.col_ref_dorms].values})

    # determine points inside/outside funnel
    data_df['position'] = 'other'
    data_df.loc[
    (data_df.dorm_ref == cwmodel.gold_dorm) & (data_df.dorm_alt == obs_method),
     'position'] = 'direct comparison'

    # get inlier/outlier 
    data_df.loc[data_df.w >= 0.6, 'trim'] = 'inlier'
    data_df.loc[data_df.w < 0.6, 'trim'] = 'outlier'

    # get plot guide
    data_df['plot_guide'] = data_df['trim'] + ', ' + data_df['position']
    plot_key = {
        'inlier, other':('o', 'seagreen', 'grey'),
        'inlier, direct comparison':('o', 'coral', 'firebrick'),
        'outlier, other':('x', 'darkgreen', 'grey'),
        'outlier, direct comparison':('x', 'firebrick', 'firebrick')
    }
        
    # construct dataframe for prediction, prev and prev_se don't matter.
    pred_df = pd.DataFrame({'obs_method': obs_method,  
                            'prev': 0.1, 
                            'prev_se': 0.1}, index=[0])
    # if it's continuous variable, take median 
    for var in continuous_variables:
        pred_df[var] = np.median(cwdata.covs[var])
    
    # predict effect
    y_pred = cwmodel.adjust_orig_vals(
        df=pred_df, 
        orig_dorms = "obs_method", 
        orig_vals_mean = "prev",  
        orig_vals_se = "prev_se"
        ).to_numpy()
    y_pred = np.ravel(y_pred)
    y_mean, y_sd = y_pred[2], y_pred[3]
    
    # Statistics in title 
    y_lower, y_upper = y_mean - 1.96*y_sd, y_mean + 1.96*y_sd
    p_value = cw.utils.p_value(np.array([y_mean]), np.array([y_sd]))[0]
    content_string = f"Mean effect: {np.round(y_mean, 3)}\
    (95% CI: {np.round(y_lower, 3)} to {np.round(y_upper, 3)});\
    p-value: {np.round(p_value, 4)}"

    # triangle
    max_se = cwdata.obs_se.max()
    se_domain = np.arange(0, max_se*1.1, max_se / 100)
    se_lower = y_mean - (se_domain*1.96)
    se_upper = y_mean + (se_domain*1.96)
    
    sns.set_style('darkgrid')
    plt.rcParams['axes.edgecolor'] = '0.15'
    plt.rcParams['axes.linewidth'] = 0.5
    plt.figure(figsize=(10,8))
    plt.fill_betweenx(se_domain, se_lower, se_upper, color='white', alpha=0.75)
    plt.axvline(y_mean, 0, 1 - (0.025*max(se_domain) / (max(se_domain)*1.025)), 
                color='black', alpha=0.75, linewidth=0.75)
    plt.plot(se_lower, se_domain, color='black', linestyle='--', linewidth=0.75)
    plt.plot(se_upper, se_domain, color='black', linestyle='--', linewidth=0.75)
    plt.ylim([-0.025*max(se_domain), max(se_domain)])
    plt.xlabel('Effect size', fontsize=10)
    plt.xticks(fontsize=10)
    plt.ylabel('Standard error', fontsize=10)
    plt.yticks(fontsize=10)
    plt.axvline(0, color='mediumseagreen', alpha=0.75, linewidth=0.75)
    # Plot inlier and outlier
    for key, value in plot_key.items():
        plt.plot(
            data_df.loc[data_df.plot_guide == key, 'y'],
            data_df.loc[data_df.plot_guide == key, 'se'],
            'o',
            markersize=5,
            marker=value[0], markerfacecolor=value[1], markeredgecolor=value[2], 
            markeredgewidth=0.6, alpha=.6, label=key
        )

    plt.legend(loc='upper left', frameon=False)
    plt.gca().invert_yaxis()
    # Plot title
    if plot_note is not None:
        plt.title(content_string, fontsize=10)
        plt.suptitle(plot_note, y=1.01, fontsize=12)
    else:
        plt.title(content_string, fontsize=10)
    # Save plots
    if write_file:
        assert cwdir is not None, "cwdir is not specified!"
        outfile = os.path.join(cwdir, file_name + '.pdf')
        plt.savefig(outfile, orientation='landscape', bbox_inches='tight')
        print(f"Funnel plot saved at {outfile}")
    else:
        plt.show()
    plt.clf()


def sizes_to_slices(sizes):
    """Converting sizes to corresponding slices.
    Args:
        sizes (numpy.dnarray):
            An array consist of non-negative number.
    Returns:
        list{slice}:
            List the slices.
    """
    slices = []
    a = 0
    b = 0
    for i, size in enumerate(sizes):
        b += size
        slices.append(slice(a, b))
        a += size

    return slices