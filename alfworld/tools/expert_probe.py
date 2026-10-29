import sys, os, time, textworld
from alfworld.agents.environment.alfred_tw_env import AlfredDemangler, AlfredInfos
game = os.path.join(sys.argv[1], sys.argv[2])
t = time.time()
infos = textworld.EnvInfos(won=True, admissible_commands=True, policy_commands=True, extras=["gamefile"])
env = textworld.start(game, request_infos=infos, wrappers=[AlfredDemangler(shuffle=False), AlfredInfos])
st = env.reset()
print("%.2fs" % (time.time() - t), st["policy_commands"])
