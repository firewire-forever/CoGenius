import os
import logging
from logging.handlers import RotatingFileHandler
from flask import has_request_context, request

class RequestFormatter(logging.Formatter):
    """
    自定义日志格式化器，添加请求相关信息
    """
    def format(self, record):
        if has_request_context():
            record.url = request.url
            record.remote_addr = request.remote_addr
            record.method = request.method
        else:
            record.url = None
            record.remote_addr = None
            record.method = None
            
        return super().format(record)

def setup_logger(app):
    import logging
    from logging.handlers import RotatingFileHandler
    import os

    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    formatter = RequestFormatter(
        '[%(asctime)s] %(remote_addr)s - %(method)s %(url)s\n'
        '%(levelname)s in %(module)s: %(message)s'
    )

    # 直接用 Flask 的 logger
    logger = app.logger
    logger.setLevel(logging.INFO)

    # 清空已有 handler，防止重复
    logger.handlers = []

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=1024 * 1024,
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    error_file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'error.log'),
        maxBytes=1024 * 1024,
        backupCount=10,
        encoding='utf-8'
    )
    error_file_handler.setFormatter(formatter)
    error_file_handler.setLevel(logging.ERROR)

    logger.addHandler(file_handler)
    logger.addHandler(error_file_handler)

    # 控制台 handler（可选）
    if app.debug:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.DEBUG)
        logger.addHandler(console_handler)

    return logger