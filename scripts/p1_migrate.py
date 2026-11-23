"""Backed-up additive medicine-evidence migration; no qualification or consent changes."""
import argparse,os,json,hashlib

def main(environment):
    os.environ['DEEPSEEKDOC_DEMO']='1' if environment=='demo' else '0'
    import local_stack as s
    values=s.config();s.ensure_private()
    if s.commerce_mode(values)!='true': raise RuntimeError('Verified commerce deployment required')
    if s.listening(s.JAVA_PORT): raise RuntimeError('Stop target stack before migrating')
    backup=s.backup(values)
    with s.database(values) as conn:
        s.query(conn,(s.ROOT/'docs/sql/P1-evidence.sql').read_text(encoding='utf-8'))
        ddl=s.query(conn,'SHOW CREATE TABLE medicine_evidence')[0][1]
    report={'passed':True,'targetFingerprint':s.target_fingerprint(values),'backup':str(backup),
            'schemaSha256':hashlib.sha256((s.ROOT/'docs/sql/P1-evidence.sql').read_bytes()).hexdigest(),
            'structureSha256':hashlib.sha256(ddl.encode()).hexdigest()}
    (s.RUN/'p1-evidence-migration.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'environment':environment,'existingProductsChanged':False}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--environment',choices=['normal','demo'],required=True);main(p.parse_args().environment)
