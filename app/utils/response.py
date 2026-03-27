from flask import jsonify
from enum import Enum

class ErrorCode(Enum):
    """
    错误码枚举类
    """
    SUCCESS = (0, "成功")
    UNKNOWN_ERROR = (9001, "未知错误")
    PARAM_ERROR = (9002, "参数错误")
    NOT_FOUND = (9003, "资源不存在")
    UNAUTHORIZED = (9004, "未授权访问")
    FORBIDDEN = (9005, "禁止访问")
    SERVER_ERROR = (9006, "服务器内部错误")
    
    # 业务相关错误码 (10000-19999)
    CASE_NOT_FOUND = (10001, "案例不存在")
    VSDL_COMPILE_ERROR = (10002, "VSDL编译失败")
    VSDL_GENERATION_FAILED = (10003, "VSDL脚本生成失败")
    LLM_API_ERROR = (10004, "LLM API调用失败")
    TERRAFORM_GENERATION_ERROR = (10005, "Terraform生成失败")
    def __init__(self, code, message):
        self.code = code
        self.message = message

class Response:
    """
    统一响应封装类
    """
    @staticmethod
    def success(data=None, message=None):
        """
        成功响应
        
        Args:
            data: 响应数据
            message: 自定义成功消息
        """
        return jsonify({
            'code': ErrorCode.SUCCESS.code,
            'message': message or ErrorCode.SUCCESS.message,
            'data': data
        })
    
    @staticmethod
    def error(error_code=ErrorCode.UNKNOWN_ERROR, message=None, data=None):
        """
        错误响应
        
        Args:
            error_code: 错误码枚举
            message: 自定义错误消息
            data: 额外的错误数据
        """
        return jsonify({
            'code': error_code.code,
            'message': message or error_code.message,
            'data': data
        })
    
    @staticmethod
    def custom_error(code, message, data=None):
        """
        自定义错误响应
        
        Args:
            code: 自定义错误码
            message: 错误消息
            data: 额外的错误数据
        """
        return jsonify({
            'code': code,
            'message': message,
            'data': data
        })
    
    @staticmethod
    def page(items, total, page, per_page):
        """
        分页数据响应
        
        Args:
            items: 当前页数据
            total: 总数据量
            page: 当前页码
            per_page: 每页数量
        """
        return jsonify({
            'code': ErrorCode.SUCCESS.code,
            'message': ErrorCode.SUCCESS.message,
            'data': {
                'items': items,
                'total': total,
                'page': page,
                'per_page': per_page,
                'pages': (total + per_page - 1) // per_page
            }
        }) 