import sys, os, time, textworld
from alfworld.agents.environment.alfred_tw_env import AlfredDemangler, AlfredInfos
root = sys.argv[1]; game = os.path.join(root, sys.argv[2])
t = time.time()
infos = textworld.EnvInfos(won=True, admissible_commands=True, extras=["gamefile"])
env = textworld.start(game, request_infos=infos, wrappers=[AlfredDemangler(shuffle=False), AlfredInfos])
st = env.reset()
print("load+reset %.2fs" % (time.time() - t))
print(repr(st.feedback[:900]))
print(st["admissible_commands"][:8], len(st["admissible_commands"]))
for a in ["look", "inventory", "fly away", st["admissible_commands"][0]]:
    st, r, d = env.step(a); print(">", a, "|", repr(st.feedback[:200]), r, d, st["won"])
