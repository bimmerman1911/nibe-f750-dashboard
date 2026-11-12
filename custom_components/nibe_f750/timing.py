"""Full-trajectory command timing improvements; never moves chart data alone."""
def _windows(result, slots):
    commands=result['commands'];windows=[]
    for width in (2,4,8):
        for i in range(0,len(commands),max(1,width//2)):
            rows=commands[i:i+width]
            if not rows or any(c.get('locked') for c in rows):continue
            start,end=rows[0]['start'],rows[-1]['end']
            overlaps=[(s,max(0,min(end,s['end'])-max(start,s['start']))) for s in result['steps']]
            duration=sum(dt for _,dt in overlaps)
            if duration<=0:continue
            price=sum(s['price']*dt for s,dt in overlaps)/duration
            # Space heating only: DHW has its own native/reserve policy.
            heat=sum(s['compressor_kw']*dt/3600 for s,dt in overlaps if s['action']=='heat')
            windows.append((i,i+len(rows),price,heat))
    return windows


def transfers(result, slots, levels):
    """Lower expensive demand and raise cheaper demand as one coupled edit.

    Try both earlier preheating and later recovery. Offset leads are simulated
    explicitly: native degree minutes determine when the compressor responds.
    """
    commands=result['commands'];windows=_windows(result,slots)
    pairs=[]
    for a in windows:
        for b in windows:
            if a[3]<=.01 or a[2]-b[2]<.05 or not (a[1]<=b[0] or b[1]<=a[0]):continue
            opportunity=(a[2]-b[2])*a[3]/max(1,a[1]-a[0])
            pairs.append((opportunity,a,b))
    pairs.sort(key=lambda p:p[0],reverse=True)
    # Round-robin among opportunities: one long window must not consume the
    # entire allowance before a different price boundary is tested.
    for lead in (0,2,4):
        for _,a,b in pairs[:12]:
            for amount in (4.,20.):
                lower=set(range(max(0,a[0]-lead),a[1]))
                raise_=set(range(max(0,b[0]-lead),b[1]))
                if lower & raise_:continue
                edited=[dict(c) for c in commands]
                for i in lower|raise_:
                    c=edited[i]
                    if c.get('locked'):continue
                    wanted=c['offset']+(-amount if i in lower else amount)
                    c['offset']=min(levels,key=lambda v:abs(v-wanted))
                yield edited


def blocks(result, levels):
    """Repair or remove demand anywhere, including early restart commands."""
    commands=result['commands']
    for width in (4,2,1,8):
        # Both directions across the complete horizon before trying finer edits.
        for amount in (4.,-4.):
            for i in range(0,len(commands),max(1,width//2)):
                edited=[dict(c) for c in commands]
                for c in edited[i:i+width]:
                    if not c.get('locked'):
                        c['offset']=min(levels,key=lambda v:abs(v-c['offset']-amount))
                yield edited


def improve(seed, slots, levels, evaluate, key, budget=None, max_evaluations=256, alternatives=()):
    """Accept only complete replays improving the same constrained objective.

    Fixed passes bound CPU work. Budget exhaustion leaves the best fully
    evaluated schedule intact and is reported, never called an optimality proof.
    All edits retain command timestamps, the cloud gate, DHW modes and locks.
    """
    best=seed;attempts=0;accepted=0;stopped=False;log=[];expanded=0;rejected=[]
    signature=lambda commands:tuple((c['offset'],c['dhw_mode']) for c in commands)
    seen={signature(seed['commands'])}
    def phases():
        # Repair several starting paths before committing to one trajectory.
        # A prefix-ranked winner can otherwise hide a cheaper repairable plan.
        for origin in alternatives:
            if origin is not seed:yield 'restart-repair',origin,blocks(origin,levels),24
        for turn in range(4):
            before=accepted
            yield 'price-transfer',best,transfers(best,slots,levels),48
            yield 'offset-timing',best,blocks(best,levels),48
            if accepted==before:break
    for name,origin,edits,allowance in phases():
        previous_best=best;winner=best;count=0
        for commands in edits:
            if budget:
                budget.check_cancelled()
                if budget.remaining()<.25:stopped=True;break
            if attempts>=max_evaluations:stopped=True;break
            sig=signature(commands)
            if sig in seen:continue
            seen.add(sig)
            candidate=evaluate(commands);attempts+=1;count+=1
            expanded+=candidate['planning']['expanded']
            if candidate['model_cost']<previous_best['model_cost'] and key(candidate)>=key(previous_best):
                rejected.append({'kind':name,'cost':candidate['model_cost'],
                    'violation':candidate['constraint_violation_score'],
                    'morning_shortfall':candidate['morning_shortfall'],
                    'objective':key(candidate)[2]})
            if key(candidate)<key(winner):winner=candidate
            if count>=allowance:break
        if winner is not previous_best:
            winner['planning']['strategy']=name
            log.append({'kind':name,'from_cost':previous_best['model_cost'],'to_cost':winner['model_cost'],
                'from_violation':previous_best['constraint_violation_score'],'to_violation':winner['constraint_violation_score'],
                'from_objective':key(previous_best)[2],'to_objective':key(winner)[2]})
            best=winner;accepted+=1
        if stopped:break
    best['planning']['timing_comparison']={'evaluated':attempts,'expanded':expanded,'accepted':accepted,'budget_limited':stopped,
        'before_cost':seed['model_cost'],'after_cost':best['model_cost'],
        'before_violation':seed['constraint_violation_score'],'after_violation':best['constraint_violation_score'],
        'before_objective':key(seed)[2],'after_objective':key(best)[2],
        'global_optimum_proven':False,'improvements':log,
        'cheaper_rejected':sorted(rejected,key=lambda r:r['cost'])[:6]}
    return best
