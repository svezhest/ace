# Рандом прогона апстрима: random.seed(0) и uuid.uuid4 из своего random.Random(0). Код апстрима не меняется.
# uuid4 апстрим берёт из os.urandom, а 8 его символов попадают в workdir python_executor, который модель видит в
# выводе инструмента (utu/tools/python_executor_toolkit.py:44-46).
import random
import uuid

random.seed(0)
_rng = random.Random(0)
uuid.uuid4 = lambda: uuid.UUID(int=_rng.getrandbits(128), version=4)
