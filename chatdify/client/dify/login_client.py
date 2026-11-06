"""登录客户端"""
import base64
from typing import Dict, Any
import requests

from chatdify.utils.exceptions import LoginError, RateLimitError, TokenError


def _encode_password(password: str) -> str:
    """
    对密码进行 Base64 编码
    Dify 1.11.2+ 要求密码经过 Base64 编码后传输
    
    Args:
        password: 原始密码
        
    Returns:
        Base64 编码后的密码
    """
    return base64.b64encode(password.encode('utf-8')).decode('utf-8')


def _error_message(error: requests.exceptions.RequestException) -> str:
    try:
        return error.response.json().get('message', str(error))
    except ValueError:
        return str(error)


class LoginClient:
    """登录客户端 - 统一管理认证 Session"""
    
    def __init__(self, base_url: str):
        """初始化客户端
        
        Args:
            base_url: API基础URL，例如 http://localhost:80
        """
        self.base_url = base_url.rstrip('/')
        # 使用 Session 来自动管理 Cookie 和 Headers
        self.session = requests.Session()
        self.session.headers['Content-Type'] = 'application/json'
    
    def _setup_auth_headers(self):
        """设置所有必要的认证 headers
        
        在登录成功后自动调用，设置：
        1. Authorization: Bearer <access_token>
        2. X-CSRF-Token: <csrf_token>
        """
        # 从 Cookie 中获取 access_token 并设置到 header
        access_token = self.session.cookies.get('access_token')
        if access_token:
            self.session.headers['Authorization'] = f'Bearer {access_token}'
        
        # 从 Cookie 中获取 CSRF token 并设置到 header
        csrf_token = self.session.cookies.get('csrf_token')
        if csrf_token:
            self.session.headers['X-CSRF-Token'] = csrf_token

    def password_login(self, email: str, password: str, remember_me: bool = False) -> Dict[str, Any]:
        """邮箱密码登录 Dify Console
        
        Args:
            email: 邮箱地址
            password: 登录密码
            remember_me: 是否记住登录状态，默认为 False
            
        Returns:
            Dict[str, Any]: 登录结果
            
        Raises:
            LoginError: 登录失败时抛出，包含具体错误信息
            RateLimitError: 登录尝试次数过多时抛出
        """
        if not email or not password:
            raise LoginError("缺少 Dify 登录凭据，请设置 CHATDIFY_DIFY_EMAIL / CHATDIFY_DIFY_PASSWORD")

        try:
            # Dify 1.11.2+ 要求密码经过 Base64 编码
            response = self.session.post(
                f'{self.base_url}/console/api/login',
                json={
                    'email': email,
                    'password': _encode_password(password),
                    'remember_me': remember_me
                }
            )
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('result') == 'success':
                # Dify 1.10.0+ 版本：token 在 cookie 中
                cookies = response.cookies.get_dict()
                
                if 'access_token' not in cookies:
                    raise LoginError("登录成功但未找到 access_token")
                
                # 登录成功后，自动设置必要的认证 headers
                self._setup_auth_headers()
                
                # 返回 token 信息（可选，主要用于调试）
                return {
                    'access_token': cookies.get('access_token'),
                    'refresh_token': cookies.get('refresh_token'),
                    'csrf_token': cookies.get('csrf_token')
                }
            else:
                raise LoginError(result.get('message', '登录失败'))
                
        except requests.exceptions.RequestException as e:
            if e.response is not None:
                if e.response.status_code == 429:
                    raise RateLimitError("登录尝试次数过多")
                raise LoginError(_error_message(e))
            raise LoginError(f"无法连接 Dify ({self.base_url}): {e}")

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """刷新访问令牌
        
        Args:
            refresh_token: 刷新令牌
            
        Returns:
            Dict: 新的令牌对
            
        Raises:
            TokenError: 刷新令牌无效
        """
        try:
            response = self.session.post(
                f'{self.base_url}/api/auth/refresh-token',
                json={'refresh_token': refresh_token}
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get('result') == 'success':
                # Dify 1.10.0+ 版本：token 在 cookie 中，session 会自动管理
                cookies = response.cookies.get_dict()
                
                if 'access_token' not in cookies:
                    raise TokenError('Token data not found in response')
                
                # 刷新 token 后，重新设置认证 headers
                self._setup_auth_headers()
                
                return {
                    'access_token': cookies.get('access_token'),
                    'refresh_token': cookies.get('refresh_token'),
                    'csrf_token': cookies.get('csrf_token')
                }
            else:
                raise TokenError(result.get('message', '刷新令牌失败'))
                
        except requests.exceptions.RequestException as e:
            if e.response is not None:
                raise TokenError(_error_message(e))
            raise TokenError(str(e))

    def logout(self) -> None:
        """登出"""
        try:
            response = self.session.post(
                f'{self.base_url}/console/api/logout'
            )
            response.raise_for_status()
        finally:
            # 清除 session cookies 和 headers
            self.session.cookies.clear()
            # 移除认证相关的 headers
            self.session.headers.pop('Authorization', None)
            self.session.headers.pop('X-CSRF-Token', None)