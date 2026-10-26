#!/usr/bin/env python3
"""Exact synthetic experiments for the evidence-source audit game.

No LLM calls, observed fraud, or banking data. All scenarios are specified
generative assumptions. SciPy/HiGHS solves finite matrix games; a separately
formulated dual certifies every reported optimization.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
from fractions import Fraction
from pathlib import Path
from clean_metadata import clean_file

import numpy as np
import scipy
from scipy.optimize import linprog

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "extended"
SEED = 20261026
SOLVER_GAPS = []
FEASIBILITY_ERRORS = []


def schedules(nchecks, budget):
    return [s for k in range(budget + 1)
            for s in itertools.combinations(range(nchecks), k)]


def source_matrix(values, coverage, source_of, schedules_, detection, common_failure):
    """A source has ONE reveal event, even if multiple checks use it.

    With probability g no source reveals. Otherwise source reveal events are
    independent Bernoulli(d_s). coverage[c,s] indicates an applicable source.
    This transparent distribution is a special case of the paper's arbitrary
    joint distribution over source-reveal vectors.
    """
    values, detection = np.asarray(values), np.asarray(detection)
    L = np.empty((len(values), len(schedules_)))
    for j, schedule in enumerate(schedules_):
        selected = sorted(set(source_of[a] for a in schedule))
        for c, value in enumerate(values):
            relevant = [s for s in selected if coverage[c, s]]
            fail = np.prod(1 - detection[relevant])
            L[c, j] = value * (common_failure + (1-common_failure)*fail)
    return L


def false_independence_matrix(values, coverage, source_of, schedules_, detection, g):
    """Ablation: preserve each individual check's marginal effectiveness,
    but incorrectly treat every check, including aliases, as independent.
    """
    marginal = (1-g)*np.asarray(detection)
    return np.array([[v*np.prod([1-marginal[source_of[a]] for a in S
                                if coverage[c, source_of[a]]])
                      for S in schedules_] for c, v in enumerate(values)])


def game_rows(matrices, leakage):
    if not 0 <= leakage <= 1:
        raise ValueError("Leakage must be in [0,1]")
    return np.vstack([(1-leakage)*L + leakage*L.max(axis=0)[None, :]
                      for L in matrices])


def evaluate(matrices, leakage, x):
    return float(np.max(game_rows(matrices, leakage) @ x))


def solve(matrices, leakage):
    """min_x max_i A_i x, with an independently solved attacker dual."""
    A = game_rows(matrices, leakage)
    m, n = A.shape
    primal = linprog(np.r_[np.zeros(n), 1.],
                     A_ub=np.c_[A, -np.ones(m)], b_ub=np.zeros(m),
                     A_eq=np.array([np.r_[np.ones(n), 0.]]), b_eq=[1.],
                     bounds=[(0, None)]*n+[(None, None)], method="highs")
    dual = linprog(np.r_[np.zeros(m), -1.],
                   A_ub=np.c_[-A.T, np.ones(n)], b_ub=np.zeros(n),
                   A_eq=np.array([np.r_[np.ones(m), 0.]]), b_eq=[1.],
                   bounds=[(0, None)]*m+[(None, None)], method="highs")
    if not primal.success or not dual.success:
        raise RuntimeError((primal.message, dual.message))
    x = primal.x[:-1]
    q = dual.x[:-1]
    upper, lower = float(np.max(A @ x)), float(np.min(q @ A))
    gap = upper-lower
    error = max(abs(x.sum()-1), abs(q.sum()-1), -x.min(), -q.min(), 0)
    SOLVER_GAPS.append(gap)
    FEASIBILITY_ERRORS.append(float(error))
    assert gap >= -1e-7 and gap < 1e-7, (upper, lower)
    assert error < 1e-8
    return {"x": x, "value": upper, "lower": lower, "gap": gap}


def exact_leakage_case():
    v = np.array([80., 60., 40.])
    L = np.repeat(v[:, None], 3, axis=1)
    np.fill_diagonal(L, 0.1*v)
    candidates = [np.array([67.,46.,4.])/117,
                  np.array([17.,10.,0.])/27, np.array([1.,0.,0.])]
    rows = []
    for lam in sorted(set(np.linspace(0, 1, 101).tolist() + [27/52, 27/37])):
        fit = solve([L], lam)
        scores = [evaluate([L], lam, x) for x in candidates]
        assert abs(fit['value']-min(scores)) < 1e-8
        rows.append({"leakage":lam, "optimal_loss":fit['value'],
                     "original_policy_loss":scores[0],
                     "fixed_policy_loss":scores[2],
                     "p1":float(fit['x'][0]), "p2":float(fit['x'][1]),
                     "p3":float(fit['x'][2])})
    # Exact rational agreement at the two breakpoints.
    t1, t2 = Fraction(27,52), Fraction(27,37)
    A = lambda z: Fraction(504,13) + z*(Fraction(8020,117)-Fraction(504,13))
    B = lambda z: Fraction(40) + z*Fraction(740,27)
    assert A(t1) == B(t1) and B(t2) == 60
    return rows


def generate_case(index):
    # An independent stream per topology makes subsets reproducible.
    rng = np.random.default_rng(SEED+index)
    values = rng.integers(30, 101, size=6).astype(float)
    coverage = np.zeros((6,5), dtype=bool)
    for c in range(6):
        coverage[c, rng.choice(5, size=int(rng.integers(2,4)), replace=False)] = True
    detection = rng.uniform(.65, .95, size=5)
    source_of = (0,0,1,1,2,3,4)
    d_a, d_b = detection.copy(), detection.copy()
    d_a[:2] *= .35
    d_b[2:] *= .35
    scenarios = [(detection,.03),(d_a,.15),(d_b,.15)]
    # Outside the specified envelope; no robustness guarantee is claimed.
    d_out = detection.copy()
    d_out[[0,2]] *= .15
    return values, coverage, source_of, scenarios, (d_out,.35)


def csv_write(name, rows):
    with (OUT/name).open('w',newline='',encoding='utf-8') as f:
        w = csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def compact_case(index, v, coverage, source_of, sc, outside):
    return {"index":index,"values":v.tolist(),"coverage":coverage.astype(int).tolist(),
            "source_of":list(source_of),
            "scenarios":[{"d":d.tolist(),"g":g} for d,g in sc],
            "outside":{"d":outside[0].tolist(),"g":outside[1]}}


def run_suite(count=100):
    rows, cases = [], []
    for index in range(count):
        v, cov, src, scenarios_, outside = generate_case(index)
        cases.append(compact_case(index,v,cov,src,scenarios_,outside))
        for budget in (1,2):
            ss = schedules(len(src),budget)
            matrices = [source_matrix(v,cov,src,ss,d,g) for d,g in scenarios_]
            naive = [false_independence_matrix(v,cov,src,ss,d,g) for d,g in scenarios_]
            heldout = sum(w*L for w,L in zip((.2,.4,.4),matrices))
            outside_L = source_matrix(v,cov,src,ss,*outside)
            # One representative per source combination eliminates duplicate
            # labels from the uniform baseline and spends exactly B checks.
            distinct = {}
            for j,S in enumerate(ss):
                keys = tuple(sorted({src[a] for a in S}))
                if len(S)==budget and len(keys)==budget:
                    distinct.setdefault(keys,j)
            uniform = np.zeros(len(ss))
            uniform[list(distinct.values())] = 1/len(distinct)
            for lam in (0.,.25,.5):
                robust = solve(matrices,lam)
                nominal = solve([matrices[0]],lam)
                average = solve([sum(matrices)/len(matrices)],lam)
                misspecified = solve(naive,lam)
                noleak = solve(matrices,0.)
                fixed = np.zeros(len(ss))
                fixed[np.argmin(game_rows(matrices,lam).max(axis=0))] = 1.
                outside_oracle = solve([outside_L],lam)
                policies = {"Uniform distinct sources":uniform,
                            "Best fixed robust schedule":fixed,
                            "Nominal minimax":nominal['x'],
                            "Average-scenario minimax":average['x'],
                            "Independent-check ablation":misspecified['x'],
                            "Hidden-selection ablation":noleak['x'],
                            "Source-aware robust":robust['x']}
                for name,x in policies.items():
                    risk = evaluate(matrices,lam,x)
                    assert risk >= robust['value']-1e-7
                    in_hull = evaluate([heldout],lam,x)
                    assert in_hull <= risk+1e-7
                    outside_risk = evaluate([outside_L],lam,x)
                    nominal_risk = evaluate([matrices[0]],lam,x)
                    # True correlated model cannot have lower residual loss
                    # than independent checks with these same marginals.
                    assert all(np.min(L-N) >= -1e-8 for L,N in zip(matrices,naive))
                    dup_mass = sum(x[j] for j,S in enumerate(ss)
                                   if len(set(src[a] for a in S)) < len(S))
                    rows.append({"case":index,"budget":budget,"leakage":lam,
                                 "policy":name,"worst_envelope_loss":risk,
                                 "normalized_envelope_loss":risk/max(v),
                                 "robust_optimum":robust['value'],
                                 "excess_over_robust":risk-robust['value'],
                                 "nominal_loss":nominal_risk,
                                 "nominal_oracle":nominal['value'],
                                 "mixture_loss":in_hull,"outside_loss":outside_risk,
                                 "outside_oracle":outside_oracle['value'],
                                 "normalized_outside_loss":outside_risk/max(v),
                                 "duplicate_schedule_mass":float(dup_mass),
                                 "ablation_predicted_bound":misspecified['value'] if name=='Independent-check ablation' else '',
                                 "robust_bound_exceeded_outside":int(outside_risk > robust['value']+1e-7) if name=='Source-aware robust' else ''})
    return rows,cases


def sampling_study(count=100):
    rows=[]
    for index in range(count):
        v,cov,src,sc,_=generate_case(index)
        ss=schedules(len(src),2)
        truth=np.array([source_matrix(v,cov,src,ss,d,g) for d,g in sc])
        optimum=solve(truth,.25)['value']
        vmax=max(v)
        K=truth.size
        for n in (50,200,1000):
            rng=np.random.default_rng(SEED+100000+index*10000+n)
            # Independent bounded observations in every route/schedule/scenario
            # cell: a Bernoulli harmful outcome times that route's loss.
            estimates=rng.binomial(n,truth/v[None,:,None])/n*v[None,:,None]
            epsilon=vmax*math.sqrt(math.log(2*K/.05)/(2*n))
            upper=np.minimum(estimates+epsilon,vmax)
            fitted=solve(estimates,.25)
            conservative=solve(upper,.25)
            error=float(np.max(np.abs(estimates-truth)))
            regret=evaluate(truth,.25,fitted['x'])-optimum
            assert regret <= 2*error+1e-7
            upper_actual=evaluate(truth,.25,conservative['x'])
            if error <= epsilon:
                assert upper_actual <= conservative['value']+1e-7
            rows.append({"case":index,"samples_per_cell":n,"cells":K,
                         "total_samples":n*K,"epsilon":epsilon,
                         "max_cell_error":error,"plug_in_regret":regret,
                         "normalized_regret":regret/vmax,
                         "uniform_event":int(error<=epsilon),
                         "upper_bound":conservative['value'],
                         "true_loss_upper_policy":upper_actual,
                         "bound_covers":int(upper_actual<=conservative['value']+1e-7)})
    return rows


def structural_checks():
    rng=np.random.default_rng(SEED+999999)
    # Direct enumeration independently checks the source-union product.
    v,cov,src,sc,_=generate_case(0)
    ss=schedules(len(src),2)
    for d,g in sc:
        actual=source_matrix(v,cov,src,ss,d,g)
        direct=np.zeros_like(actual)
        for bits in itertools.product((0,1),repeat=5):
            prob=(1-g)*np.prod([d[s] if bit else 1-d[s] for s,bit in enumerate(bits)])
            if not any(bits): prob+=g
            for c,value in enumerate(v):
                for j,S in enumerate(ss):
                    if not any(cov[c,src[a]] and bits[src[a]] for a in S):
                        direct[c,j]+=prob*value
        assert np.max(np.abs(direct-actual))<1e-9
    # Duplicate source inspection changes nothing in the correct model.
    L=source_matrix(v,cov,src,ss,*sc[0])
    assert np.max(np.abs(L[:,ss.index((0,))]-L[:,ss.index((0,1))]))<1e-10
    # Exhaustively check the independence-blind approximation counterexample.
    for k in range(1,7):
        alias_sources = (0,)*k + tuple(range(1,k))
        detection = [Fraction(9,10)] + [Fraction(4,5)]*(k-1)
        true_best, naive_best, naive_actual = Fraction(1), Fraction(1), None
        for S in itertools.combinations(range(2*k-1),k):
            truth=math.prod(1-detection[s] for s in set(alias_sources[a] for a in S))
            naive=math.prod(1-detection[alias_sources[a]] for a in S)
            true_best=min(true_best,truth)
            if naive<naive_best:
                naive_best,naive_actual=naive,truth
        assert true_best==Fraction(1,10)*Fraction(1,5)**(k-1)
        assert naive_actual/true_best==5**(k-1)
    # Uniform matrix perturbations: objective and value are 1-Lipschitz.
    for _ in range(30):
        A=rng.uniform(0,100,(4,6))
        B=np.clip(A+rng.uniform(-2,2,A.shape),0,100)
        x=rng.dirichlet(np.ones(6)); lam=float(rng.random())
        eps=float(np.max(np.abs(A-B)))
        assert abs(evaluate([A],lam,x)-evaluate([B],lam,x))<=eps+1e-9
        a,b=solve([A],lam),solve([B],lam)
        assert abs(a['value']-b['value'])<=eps+1e-8
        assert evaluate([A],lam,b['x'])-a['value']<=2*eps+1e-8
        f0,f1=solve([A],0)['value'],solve([A],1)['value']
        assert a['value']>= (1-lam)*f0+lam*f1-1e-8
    return {"joint_state_enumeration":"passed","duplicate_invariance":"passed",
            "alias_counterexample_exhaustive_k1_to_k6":"passed",
            "perturbation_and_regret_bounds":"passed","leakage_concavity":"passed"}


def summarize(rows,samples):
    policies=list(dict.fromkeys(r['policy'] for r in rows))
    summary=[]
    for policy in policies:
        rr=[r for r in rows if r['policy']==policy]
        losses=np.array([r['normalized_envelope_loss'] for r in rr])
        gaps=np.array([r['excess_over_robust'] for r in rr])
        summary.append({"policy":policy,"instances":len(rr),
                        "mean_normalized_envelope_loss":float(losses.mean()),
                        "median_excess_loss":float(np.median(gaps)),
                        "p95_excess_loss":float(np.quantile(gaps,.95)),
                        "mean_normalized_outside_loss":float(np.mean([r['normalized_outside_loss'] for r in rr])),
                        "mean_duplicate_mass":float(np.mean([r['duplicate_schedule_mass'] for r in rr]))})
    robust=[r for r in rows if r['policy']=='Source-aware robust']
    nominal=[r for r in rows if r['policy']=='Nominal minimax']
    ablation=[r for r in rows if r['policy']=='Independent-check ablation']
    sr=[]
    for n in (50,200,1000):
        rr=[r for r in samples if r['samples_per_cell']==n]
        sr.append({"samples_per_cell":n,"replicates":len(rr),
                   "mean_normalized_regret":float(np.mean([r['normalized_regret'] for r in rr])),
                   "max_normalized_regret":float(np.max([r['normalized_regret'] for r in rr])),
                   "uniform_events":sum(r['uniform_event'] for r in rr),
                   "bound_covers":sum(r['bound_covers'] for r in rr)})
    return {"policies":summary,"sampling":sr,
            "mean_nominal_price_of_robustness":float(np.mean([r['nominal_loss']-r['nominal_oracle'] for r in robust])),
            "robust_worse_outside_than_nominal":sum(r['outside_loss']>n['outside_loss']+1e-7 for r,n in zip(robust,nominal)),
            "robust_envelope_exceeded_outside":sum(r['robust_bound_exceeded_outside'] for r in robust),
            "false_independence_bound_failures":sum(r['worst_envelope_loss']>r['ablation_predicted_bound']+1e-7 for r in ablation)}


def figure(leakage,summary):
    os.environ.setdefault('MPLCONFIGDIR','/tmp/ai-heist-matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(1,2,figsize=(11,3.7),layout='constrained')
    for key,label,style in [('optimal_loss','Reoptimized','-'),('original_policy_loss','Original policy','--'),('fixed_policy_loss','Always check route 1',':')]:
        ax[0].plot([r['leakage'] for r in leakage],[r[key] for r in leakage],style,label=label)
    for x in (27/52,27/37): ax[0].axvline(x,color='gray',alpha=.4,lw=.8)
    ax[0].set(xlabel='Probability selected audit is disclosed',ylabel='Expected loss (assumed units)',title='A. Exact policy transitions')
    ax[0].legend(frameon=False,fontsize=8)
    pp=summary['policies']
    labels=['Uniform','Best fixed','Nominal','Average','Independent','No disclosure','Robust']
    ax[1].barh(labels,[r['mean_normalized_envelope_loss'] for r in pp],color=['#8299aa']*6+['#17697a'])
    ax[1].invert_yaxis()
    ax[1].set(xlabel='Mean worst-envelope loss / largest route loss',title='B. 600 synthetic instances')
    for a in ax:a.grid(axis='x',alpha=.15)
    fig.savefig(OUT/'extended_results.pdf')
    fig.savefig(OUT/'extended_results.png',dpi=220)
    plt.close(fig)
    clean_file(OUT/'extended_results.pdf')
    clean_file(OUT/'extended_results.png')


def write_tex(summary):
    lines=[r'\begin{tabular}{@{}lrrrr@{}}',r'\toprule',
           r'Policy & Envelope & Median gap & 95th gap & Outside \\',r'\midrule']
    names={'Uniform distinct sources':'Uniform distinct sources','Best fixed robust schedule':'Best fixed (robust)',
           'Nominal minimax':'Nominal minimax','Average-scenario minimax':'Average-scenario minimax',
           'Independent-check ablation':'Independent-check ablation','Hidden-selection ablation':'Hidden-selection ablation',
           'Source-aware robust':'Source-aware robust'}
    for r in summary['policies']:
        lines.append(f"{names[r['policy']]} & {r['mean_normalized_envelope_loss']:.3f} & {r['median_excess_loss']:.2f} & {r['p95_excess_loss']:.2f} & {r['mean_normalized_outside_loss']:.3f} " + r'\\')
    lines += [r'\bottomrule',r'\end{tabular}']
    (OUT/'policy_table.tex').write_text('\n'.join(lines)+'\n')
    lines=[r'\begin{tabular}{@{}rrrrr@{}}',r'\toprule',
           r'$n$ per cell & Total draws & Mean regret/$V$ & Max regret/$V$ & Bound coverage \\',r'\midrule']
    for r in summary['sampling']:
        lines.append(f"{r['samples_per_cell']} & {r['samples_per_cell']*522:,} & {r['mean_normalized_regret']:.4f} & {r['max_normalized_regret']:.4f} & {r['bound_covers']}/{r['replicates']} "+r'\\')
    lines += [r'\bottomrule',r'\end{tabular}']
    (OUT/'sampling_table.tex').write_text('\n'.join(lines)+'\n')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    checks=structural_checks()
    leakage=exact_leakage_case()
    rows,cases=run_suite()
    samples=sampling_study()
    summary=summarize(rows,samples)
    csv_write('leakage_curve.csv',leakage)
    csv_write('all_policy_results.csv',rows)
    csv_write('sampling_results.csv',samples)
    csv_write('policy_summary.csv',summary['policies'])
    (OUT/'instances.json').write_text(json.dumps(cases,indent=2)+'\n')
    figure(leakage,summary)
    write_tex(summary)
    summary.update({'study_type':'Synthetic finite games; no LLM or bank experiments',
                    'seed':SEED,'topologies':100,'policy_instances':600,
                    'sampling_replicates':300,'solves':len(SOLVER_GAPS),
                    'max_primal_dual_gap':float(max(SOLVER_GAPS)),
                    'max_feasibility_error':float(max(FEASIBILITY_ERRORS)),
                    'checks':checks})
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir())
            if p.is_file() and p.name not in ('manifest.json',)}
    hashes['../../analysis/evidence_audit.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    hashes['../../analysis/clean_metadata.py']=hashlib.sha256((ROOT/'analysis/clean_metadata.py').read_bytes()).hexdigest()
    (OUT/'manifest.json').write_text(json.dumps(hashes,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
