#!/usr/bin/env python3
"""Find review candidates, never change the benchmark registry (no AA)."""
import csv, datetime as dt, io, json, os, re, sys, tempfile, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path.home()/'scratch/DimResearchS/freetokens-watch/evidence-candidates.json'
TODAY = dt.date.today().isoformat()
def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'freetokens-evidence-scan/1.0'})
    with urllib.request.urlopen(req,timeout=25) as res: return res.read(12_000_000)
def norm(s): return re.sub(r'[^a-z0-9]','',str(s).lower())
def main():
    models=json.loads((ROOT/'data/models.json').read_text()); lanes=json.loads((ROOT/'data/lanes.json').read_text()); scores=json.loads((ROOT/'data/ft_scores.json').read_text())['scores']; bench=json.loads((ROOT/'data/benchmarks.json').read_text())
    ids={l['model'] for l in lanes if l['status'] in ('live','listed') and scores[l['model']].get('evidence',0)<3}; selected=[m for m in models if m['id'] in ids]; names={}
    for m in selected:
        for name in (m['name'],m['id']): names.setdefault(norm(re.sub(r'\s*\(stealth\)$','',name,flags=re.I)),set()).add(m['id'])
    candidates=[]; errors=[]
    def add(mid,url,bid,val,kind,extra=''):
        candidates.append(dict(model=mid,url=url,benchmark=bid,value=val,source_kind=kind,fetched=TODAY,detail=extra))
    # Epoch's own CSVs only; never *_external or files mentioning Artificial Analysis.
    try:
        z=zipfile.ZipFile(io.BytesIO(get('https://epoch.ai/data/benchmark_data.zip')))
        for info in z.infolist():
            if not info.filename.endswith('.csv') or info.file_size>8_000_000 or info.filename.endswith('_external.csv'): continue
            raw=z.read(info).decode('utf-8-sig','replace')
            if 'artificialanalysis' in raw.lower(): continue
            for row in csv.DictReader(io.StringIO(raw)):
                model=row.get('Model version',''); model=re.sub(r'_(?:max|high|medium|low|xhigh|default)$','',model,flags=re.I)
                hit=names.get(norm(model),set()); value=row.get('Best score (across scorers)') or row.get('mean_score')
                if len(hit)==1 and value:
                    try: add(next(iter(hit)),'https://epoch.ai/benchmarks',Path(info.filename).stem,round(float(value)*100,4),'independent','Epoch raw; verify model and benchmark')
                    except ValueError: pass
    except Exception as e: errors.append('Epoch:'+type(e).__name__)
    # HF model cards already explicitly linked to a model: extract numeric rows only as candidates.
    cards={}
    for c in bench['claims']:
        match=re.match(r'https://huggingface\.co/([^/\s]+)/([^/\s?#]+)',c.get('url',''))
        if c['model'] in ids and match and match.group(1) not in ('datasets','spaces'):
            cards.setdefault(f'https://huggingface.co/{match.group(1)}/{match.group(2)}',set()).add(c['model'])
    def card(url):
        text=get(url+'/raw/main/README.md').decode('utf-8','replace'); rows=[]
        for line in text.splitlines():
            if '|' not in line or not re.search(r'(?i)gpqa|humanity.s last exam|terminal.bench|swe.bench|livecodebench',line): continue
            cells=[x.strip(' *`') for x in line.strip().strip('|').split('|')];
            if len(cells)>1:
                m=re.search(r'(?<![\d.])(\d+(?:\.\d+)?)\s*%?',cells[1])
                if m: rows.append((cells[0],float(m.group(1))))
        return rows
    with ThreadPoolExecutor(max_workers=6) as pool:
        fs={pool.submit(card,u):u for u in cards}
        for f in as_completed(fs):
            u=fs[f]
            try:
                for b,v in f.result():
                    for mid in cards[u]: add(mid,u,b,v,'vendor','card table candidate; verify column and variant')
            except Exception as e: errors.append('HF:'+type(e).__name__)
    # OpenRouter GPQA HTML: only exact free model IDs, one public row per model.
    class Table(HTMLParser):
        def __init__(self): super().__init__(); self.inrow=False; self.href=[]; self.text=[]; self.rows=[]
        def handle_starttag(self,tag,attrs):
            if tag=='tr': self.inrow=True; self.href=[]; self.text=[]
            if self.inrow and tag=='a': self.href += [dict(attrs).get('href','')]
        def handle_data(self,data):
            if self.inrow: self.text.append(data.strip())
        def handle_endtag(self,tag):
            if tag=='tr' and self.inrow: self.rows.append((self.href,' '.join(x for x in self.text if x))); self.inrow=False
    try:
        parser=Table();parser.feed(get('https://openrouter.ai/benchmarks/gpqa-diamond').decode('utf-8','replace'))
        modelids={l['model_id'].removesuffix(':free').lower():l['model'] for l in lanes if l['model'] in ids and l.get('model_id')}
        for hrefs,text in parser.rows:
            vals=re.findall(r'(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%',text)
            if not vals: continue
            for href in hrefs:
                mid=modelids.get(href.strip('/').lower())
                if mid: add(mid,'https://openrouter.ai/benchmarks/gpqa-diamond','gpqa_diamond',float(vals[0]),'independent','OpenRouter default route; verify match and run date')
    except Exception as e: errors.append('OpenRouter:'+type(e).__name__)
    unique={(x['model'],x['url'],x['benchmark'],x['value']):x for x in candidates}; data={'generated':TODAY,'models_checked':len(selected),'candidates':list(unique.values()),'errors':errors,'note':'Unverified candidates; never automatically ingest. Epoch AI data CC BY 4.0.'}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=OUT.parent,delete=False,encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n'); temp=f.name
    os.replace(temp,OUT)
    print(f"FTI evidence: {len(selected)} models, {len(unique)} candidates, {len(errors)} source errors; review {OUT}")
    return 1 if len(errors)>0 and not unique else 0
if __name__=='__main__': sys.exit(main())
