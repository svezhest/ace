# имена временных файлов tempfile (в них DC пишет код модели, путь виден в traceback) — от своего Random с сидом 0
import os, random, tempfile; s = tempfile._get_candidate_names(); s._rng, s._rng_pid = random.Random(0), os.getpid()
