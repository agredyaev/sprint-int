#!/usr/bin/env python3
"""Strict schema and publication-gate validation for executive-only JSON.
Never ingest full Jira/Confluence fields or unapproved outputs.
"""
from __future__ import annotations
import re
import math
from datetime import datetime, date
from urllib.parse import urlparse

STATUS={'DELIVERED','PROGRESSING','BLOCKED','AT_RISK','NO_PROGRESS','UNKNOWN'}
REQUIRED_METRICS={'material_outcomes','blocked_initiatives','at_risk_initiatives','verified_time_saved_hours','manual_operations','automation_candidates','automation_delivered','active_initiatives'}
GATES={'classification','scope','evidence','sharpwriter','publication'}
ALLOWED_TOP={'sprint','metrics','epics','dependencies','quality'}
ALLOWED_SPRINT={'schema_version','id','started_on','ended_on','period_label','team','executive_summary','pulse','attention','attention_owner','reviewed_issues','published_at','is_demo'}
ALLOWED_EPIC={'jira_key','title','domain','category','delivery_team','reporting_scope','status','importance','highlight_rank','objective','delivered','impact','planned_next','risk','jira_url','tasks'}
ALLOWED_TASK={'jira_key','title','status','delivery_team','outcome','jira_url'}
ALLOWED_DEP={'epic_key','jira_key','title','team','status','impact','planned_next','jira_url'}
ALLOWED_QUALITY=GATES
LIMITS={'executive_summary':360,'pulse':350,'attention':230,'attention_owner':120,'objective':260,'delivered':280,'impact':220,'planned_next':220,'risk':180,'outcome':240}
KEY_RE=re.compile(r'^[A-Z][A-Z0-9_]+-\d+$')
ID_RE=re.compile(r'^[0-9A-Za-z._-]{1,48}$')
# V1 is read-only legacy. V2 is required for all new snapshots.
SCHEMA_VERSIONS={1,2}
V2_OPTIONAL_METRICS={'customer_impact_score'}
FLOAT_METRICS={'verified_time_saved_hours', 'customer_impact_score'}

def must_fields(d,allowed,required,where):
    if not isinstance(d,dict): raise ValueError(f'{where} must be an object')
    extra=set(d)-set(allowed)
    if extra: raise ValueError(f'{where}: unexpected fields {sorted(extra)} (raw content is forbidden)')
    missing=set(required)-set(d)
    if missing: raise ValueError(f'{where}: missing fields {sorted(missing)}')

def short(value,name,maxlen,allow_empty=False):
    if not isinstance(value,str):raise ValueError(f'{name} must be a string')
    value=value.strip()
    if not allow_empty and not value:raise ValueError(f'{name} cannot be empty')
    if len(value)>maxlen:raise ValueError(f'{name} exceeds {maxlen} characters')
    if any(ord(c)<32 and c not in '\n\t' for c in value):raise ValueError(f'{name} contains control character')
    return value

def url(value,where):
    value=short(value,where,300)
    u=urlparse(value)
    if u.scheme!='https' or not u.netloc or u.username or u.password or u.fragment:
        raise ValueError(f'{where} must be an absolute https Jira URL')
    if not ('/browse/' in u.path or '/jira/' in u.path):
        raise ValueError(f'{where} must link to a Jira issue')
    return value

def key(value,where):
    if not isinstance(value,str) or not KEY_RE.fullmatch(value):raise ValueError(f'{where} must be a Jira key')
    return value

def validate(p):
    must_fields(p,ALLOWED_TOP,ALLOWED_TOP,'payload')
    s=p['sprint'];must_fields(s,ALLOWED_SPRINT,{'id','started_on','ended_on','period_label','executive_summary','pulse','attention','reviewed_issues','published_at'},'sprint')
    version=s.get('schema_version',1)
    if type(version) is not int or version not in SCHEMA_VERSIONS:
        raise ValueError('Unsupported sprint schema_version')
    if not ID_RE.fullmatch(str(s['id'])):raise ValueError('Invalid sprint id')
    a,b=date.fromisoformat(s['started_on']),date.fromisoformat(s['ended_on'])
    if a>b:raise ValueError('Sprint date range reversed')
    datetime.fromisoformat(s['published_at'].replace('Z','+00:00'))
    if type(s['reviewed_issues']) is not int or s['reviewed_issues']<0:raise ValueError('reviewed_issues invalid')
    if type(s.get('is_demo',False)) is not bool:raise ValueError('is_demo must be boolean')
    for f in ('period_label','team','executive_summary','pulse','attention','attention_owner'):
        if f in s:short(s[f],'sprint.'+f,LIMITS.get(f,120), f in ('attention','attention_owner'))
    q=p['quality'];must_fields(q,ALLOWED_QUALITY,GATES,'quality')
    if any(q[k]!='passed' for k in GATES):raise ValueError('All five publication gates must have passed; sharpwriter cannot be assumed')
    metrics=p['metrics']
    if not isinstance(metrics,dict) or not REQUIRED_METRICS<=metrics.keys():raise ValueError('Missing required executive metrics')
    optional=V2_OPTIONAL_METRICS if version>=2 else set()
    if set(metrics)-(REQUIRED_METRICS|optional):
        raise ValueError('Unrecognized metric; expand the schema deliberately')
    for mk,mv in metrics.items():
        if mv is None and (mk in optional or mk == 'verified_time_saved_hours'):
            continue  # Unknown/insufficient evidence. Never coerce to zero.
        if mk in FLOAT_METRICS:
            valid = type(mv) in (int, float) and math.isfinite(mv)
        else:
            valid = type(mv) is int  # BIGINT counts: no fractions, booleans or coercion.
        if not valid or mv<0 or mv>1000000:
            raise ValueError(f'Invalid metric {mk}')
        if mk=='customer_impact_score' and mv>100:
            raise ValueError('customer_impact_score must be between 0 and 100')
    epics=p['epics']; deps=p['dependencies']
    if not isinstance(epics,list) or not isinstance(deps,list):raise ValueError('epics/dependencies must be arrays')
    ekeys=set(); ranks=set(); taskkeys=set()
    for i,e in enumerate(epics):
        loc=f'epics[{i}]';must_fields(e,ALLOWED_EPIC,{'jira_key','title','domain','category','status','objective','delivered','planned_next','jira_url','tasks'},loc)
        ek=key(e['jira_key'],loc+'.jira_key')
        if ek in ekeys:raise ValueError('Duplicate epic')
        ekeys.add(ek)
        short(e['title'],loc+'.title',45)
        for f in ('domain','category','delivery_team','reporting_scope','status','importance'):short(e.get(f,{'delivery_team':'Reporting','reporting_scope':'in_scope','importance':'normal'}.get(f,'')),loc+'.'+f,80)
        if e['category'] not in ('product','strategic') or e.get('reporting_scope','in_scope')!='in_scope' or e.get('delivery_team','Reporting')!='Reporting':raise ValueError(f'{loc} must be Reporting owned; DWH/operations never go in portfolio')
        if e['status'] not in STATUS:raise ValueError('Invalid epic status')
        rank=e.get('highlight_rank')
        if rank is not None:
            if type(rank) is not int or rank not in range(1,6) or rank in ranks:raise ValueError('Invalid or repeated highlight rank')
            ranks.add(rank)
        for f in ('objective','delivered','impact','planned_next','risk'):
            if f in e:short(e[f],loc+'.'+f,LIMITS[f],f in ('impact','risk'))
        url(e['jira_url'],loc+'.jira_url')
        if not isinstance(e['tasks'],list):raise ValueError('tasks must be a list')
        for j,t in enumerate(e['tasks']):
            loc2=f'{loc}.tasks[{j}]';must_fields(t,ALLOWED_TASK,{'jira_key','title','status','outcome','jira_url'},loc2)
            tk=key(t['jira_key'],loc2+'.jira_key')
            if tk in taskkeys:raise ValueError('Duplicate task')
            taskkeys.add(tk)
            short(t['title'],loc2+'.title',45);short(t['outcome'],loc2+'.outcome',LIMITS['outcome'])
            if t['status'] not in STATUS or t.get('delivery_team','Reporting')!='Reporting':raise ValueError('Only Reporting task highlights permitted')
            url(t['jira_url'],loc2+'.jira_url')
    for i,d in enumerate(deps):
        loc=f'dependencies[{i}]';must_fields(d,ALLOWED_DEP,ALLOWED_DEP,loc)
        if key(d['epic_key'],loc+'.epic_key') not in ekeys:raise ValueError('Dependency has no Reporting epic')
        key(d['jira_key'],loc+'.jira_key');short(d['title'],loc+'.title',45)
        short(d['team'],loc+'.team',80)
        if d['status'] not in STATUS:raise ValueError('Invalid dependency status')
        for f in ('impact','planned_next'):short(d[f],loc+'.'+f,LIMITS[f])
        url(d['jira_url'],loc+'.jira_url')
    if p['metrics']['active_initiatives']!=len(epics):raise ValueError('active_initiatives must equal Reporting portfolio count')
    if p['metrics']['blocked_initiatives']!=sum(e['status']=='BLOCKED' for e in epics):raise ValueError('blocked initiative metric mismatch')
    if p['metrics']['at_risk_initiatives']!=sum(e['status']=='AT_RISK' for e in epics):raise ValueError('at-risk initiative metric mismatch')
    if p['metrics']['material_outcomes'] < len(ranks):
        raise ValueError('material_outcomes cannot be less than selected material highlights')
    if ranks and ranks!=set(range(1,len(ranks)+1)):raise ValueError('Highlight ranks should be contiguous from one')
    return p
