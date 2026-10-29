"""Достаёт записанные report из логов сессий исследователя: python3 reports_dump.py TAG[#i] ..."""
import glob, json, os, sys

LOGS = os.path.expanduser("~/Projects/nrhsi/researcher/logs")


def log_of(tag):
    ps = [p for p in glob.glob(f"{LOGS}/*_{tag}.jsonl")]
    assert len(ps) == 1, (tag, ps)
    return ps[0]


def reports(tag):
    """-> (meta, [(номер, args)]) — report с записью recorded в ходах (type=turn)."""
    meta, out = None, []
    for l in open(log_of(tag)):
        r = json.loads(l)
        if r["type"] == "meta":
            meta = r
        if r["type"] == "turn":
            for res in r.get("results", []):
                if res.get("name") == "report" and res.get("recorded"):
                    out.append((res["recorded"], json.loads(res["arguments"])))
    return meta, out


if __name__ == "__main__":
    for a in sys.argv[1:]:
        tag, _, i = a.partition("#")
        meta, rs = reports(tag)
        for n, x in rs:
            if not i or int(i) == n:
                print(f"=== {tag} #{n} [{x.get('kind')}] runs={meta['runs']}\n{x.get('observation')}\nEV: "
                      + json.dumps(x.get("evidence"), ensure_ascii=False, indent=0) + "\n")
