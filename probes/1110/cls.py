import json,sys,re
for name in sys.argv[1:]:
    print("=====",name.split("/")[-1])
    for k,l in enumerate(open(name)):
        o=json.loads(l)
        if "error" in o: print(k,"ERR",o["error"][:80]); continue
        rs=len(o.get("reasoning") or "")
        print(f"#{k} gen={o['usage'].get('completion_tokens')} reasoning_chars={rs} say={(o['content'] or '')[:120]!r}")
        for c in o["calls"]:
            try: a=json.loads(c["arguments"])
            except Exception: print("    bad args"); continue
            n=a.get("new_string","")
            for x in n.splitlines():
                if re.search(r"^\s*(if|elif|return|while|for)\b",x) and not re.search(r"return None|return Hint|return Block|return False$|return True$",x): print("     |",x.strip()[:150])
