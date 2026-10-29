import json, sys
msgs = [json.loads(l) for l in open(sys.argv[1])]
print(msgs[1]["content"].split("AVAILABLE")[0][-160:])
for x in msgs[2:]:
    if x["role"] == "assistant":
        tc = x.get("tool_calls")
        a = json.loads(tc[0]["function"]["arguments"]) if tc else None
        print("A:", (x["content"] or "")[:110].replace("\n", " "), "->", a)
    elif x["role"] == "tool":
        print("   T:", x["content"].split(" AVAILABLE")[0][:120])
    else:
        print("   U:", x["content"][:60])
