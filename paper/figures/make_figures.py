
import json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
plt.rcParams.update({'font.family':'serif','font.size':9,'axes.titlesize':10,'axes.labelsize':9,'legend.fontsize':8,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':160})
COL={'V4 Flash':'#0072B2','V4.1 Flash':'#009E73','M3':'#D55E00'}
ARMS=['patch-find-replace','find-replace','find-replace-numkey','rewrite']
LABELS=['local patch','global find/replace','global + keys','rewrite']
RUNS={'V4 Flash':'dta19-doc-1shot-','V4.1 Flash':'v41-dta19-doc-1shot-','M3':'mm3-dta19-doc-1shot-'}
ARM_KEYS={'patch-find-replace':'patch_find_replace','find-replace':'find_replace_anthropic_style','find-replace-numkey':'find_replace_numkey','rewrite':'rewrite_anthropic_style'}
def load(prefix, short):
    r=json.loads((ROOT/'runs'/(prefix+short)/'report.json').read_text(encoding='utf-8'))
    rows=r['per_sample'][ARM_KEYS[short]]
    return np.array([v['score']['cmer'] for v in rows.values() if v.get('score')]), rows
fig,axes=plt.subplots(1,2,figsize=(6.8,2.8),gridspec_kw={'width_ratios':[1.35,1]})
x=np.arange(len(ARMS)); width=.24
for j,(model,prefix) in enumerate(RUNS.items()):
    med=[]; p90=[]
    for short in ARMS:
        v,_=load(prefix,short); med.append(np.median(v)); p90.append(np.quantile(v,.9,method='higher'))
    axes[0].bar(x+(j-1)*width,med,width,label=model,color=COL[model],alpha=.92)
    axes[1].bar(x+(j-1)*width,p90,width,label=model,color=COL[model],alpha=.92)
for ax,title in zip(axes,['Median cMER','P90 cMER (tail)']):
    ax.set_xticks(x); ax.set_xticklabels(LABELS,rotation=28,ha='right'); ax.set_title(title); ax.grid(axis='y',alpha=.2); ax.set_ylim(bottom=0)
axes[0].set_ylabel('lower is better'); axes[1].legend(frameon=False,loc='upper left'); fig.tight_layout(w_pad=1.3)
fig.savefig(OUT/'interface-distributions.pdf',bbox_inches='tight'); fig.savefig(OUT/'interface-distributions.png',dpi=300,bbox_inches='tight'); plt.close(fig)
shorts=['patch-find-replace','find-replace','find-replace-numkey','find-replace-blocked','patch-find-replace-noatt','patch-find-replace-unstable','rewrite','rewrite-numkey']
labels=['local patch','global F/R','global + keys','blocked F/R','patch no-attn','unstable IDs','rewrite','rewrite + keys']
fig,ax=plt.subplots(figsize=(6.8,2.8)); done=[]; edited=[]
for short in shorts:
    arm={'patch-find-replace':'patch_find_replace','find-replace':'find_replace_anthropic_style','find-replace-numkey':'find_replace_numkey','find-replace-blocked':'find_replace_blocked','patch-find-replace-noatt':'patch_find_replace_noatt','patch-find-replace-unstable':'patch_find_replace_unstable','rewrite':'rewrite_anthropic_style','rewrite-numkey':'rewrite_numkey'}[short]
    r=json.loads((ROOT/'runs'/('mm3-dta19-doc-1shot-'+short)/'report.json').read_text(encoding='utf-8')); rows=r['per_sample'][arm]
    done.append(sum(v['status']=='done' for v in rows.values())/len(rows)*100); edited.append(sum(v['score']['edit_spans']>0 for v in rows.values())/len(rows)*100)
xx=np.arange(len(labels)); w=.36; ax.bar(xx-w/2,done,w,label='protocol completed',color='#56B4E9'); ax.bar(xx+w/2,edited,w,label='effective edits',color='#D55E00')
ax.set_ylabel('tasks (%)'); ax.set_ylim(0,105); ax.set_xticks(xx); ax.set_xticklabels(labels,rotation=32,ha='right'); ax.grid(axis='y',alpha=.2); ax.legend(frameon=False,ncol=2,loc='upper left'); fig.tight_layout()
fig.savefig(OUT/'m3-compliance.pdf',bbox_inches='tight'); fig.savefig(OUT/'m3-compliance.png',dpi=300,bbox_inches='tight')
