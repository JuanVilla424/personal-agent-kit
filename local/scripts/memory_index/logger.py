import logging
import sys
import os

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def setup_logger(name, level=logging.INFO, log_file=None):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    os.makedirs(_LOG_DIR, exist_ok=True)

    if not logger.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(sh)

        if log_file:
            fh = logging.FileHandler(log_file)
            fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            logger.addHandler(fh)

    return logger


logger = setup_logger(
    "memory-index",
    log_file=os.path.join(_LOG_DIR, "memory-index.log"),
)
