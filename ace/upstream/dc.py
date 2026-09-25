"""Dynamic Cheatsheet апстрима (dynamic_cheatsheet/language_model.py): параметры вызовов генератора, куратора и
синтеза, разбор блока <cheatsheet>."""
from .. import parse
from ..model import Reader

CHEATSHEET = Reader(text=parse.opened("cheatsheet"))   # extract_cheatsheet апстрима
MAX_TOKENS = 2048           # --max_tokens апстрима
TOKENS = 2                  # куратор и синтез пишут до 2 * max_tokens, как в апстриме


def dc_params(tokens=MAX_TOKENS):
    """Параметры всех вызовов апстрима (_generate_openai: T = 0.0 и max_completion_tokens)."""
    return dict(temperature=0.0, max_completion_tokens=tokens)
