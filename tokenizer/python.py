import logging

logger = logging.getLogger("radar.tokenizer")

def cron(submission, config):
    """
    Tokenizes Python code to a sequence of high level structural tokens
    that are independent from names or values.
    
    """
    logger.error("Missing Python tokenizer")
