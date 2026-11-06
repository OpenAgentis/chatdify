import requests
from typing import Optional, Dict, Any, Tuple
import yaml
import os
import json
from typing import List
import mimetypes
import time
from requests_toolbelt.multipart.encoder import MultipartEncoder

from chatdify.client.dify.login_client import LoginClient
from chatdify.settings import get_settings
from chatdify.utils.logging import get_logger


logger = get_logger(__name__)


class AppClient:
    def __init__(self, base_url: str, email: Optional[str] = None, password: Optional[str] = None):
        """初始化客户端
        
        Args:
            base_url: Dify 地址，例如 http://localhost
            email: Dify Console 登录邮箱，默认读取配置 dify_email
            password: Dify Console 登录密码，默认读取配置 dify_password
        """
        self.base_url = base_url.rstrip('/')
        settings = get_settings()
        self._email = email or settings.dify_email
        self._password = password or settings.dify_password
        
        self._get_authorization()
    
    def _get_authorization(self):
        """获取认证信息
        
        创建 LoginClient 并登录，所有认证细节（Session、Cookie、Headers）
        都由 LoginClient 统一管理
        """
        self.login_client = LoginClient(self.base_url)
        self.login_client.password_login(email=self._email, password=self._password)
        
        # 共享 LoginClient 的 session
        # LoginClient 已经在登录时自动设置好所有必要的认证信息：
        # - Cookie (access_token, refresh_token, csrf_token)
        # - Authorization header (Bearer token)
        # - X-CSRF-Token header
        self.session = self.login_client.session

    def import_app(self, 
                   mode: str,
                   yaml_content: Optional[str] = None,
                   yaml_url: Optional[str] = None,
                   name: Optional[str] = None,
                   description: Optional[str] = None,
                   icon_type: Optional[str] = None,
                   icon: Optional[str] = None,
                   icon_background: Optional[str] = None,
                   app_id: Optional[str] = None) -> Dict[str, Any]:
        """导入应用
        
        Args:
            mode: 导入模式
            yaml_content: YAML内容
            yaml_url: YAML URL地址
            name: 应用名称
            description: 应用描述
            icon_type: 图标类型
            icon: 图标
            icon_background: 图标背景
            app_id: 应用ID
            
        Returns:
            Dict: 导入结果
        """
        data = {
            'mode': mode,
            'yaml_content': yaml_content,
            'yaml_url': yaml_url,
            'name': name,
            'description': description,
            'icon_type': icon_type,
            'icon': icon,
            'icon_background': icon_background,
            'app_id': app_id
        }
        
        # 移除None值
        data = {k: v for k, v in data.items() if v is not None}
        
        
        response = self.session.post(
            f'{self.base_url}/console/api/apps/imports',
            json=data
        )
        
        
        if response.status_code != 200:
            logger.error(f"Response body: {response.text}")
        
        response.raise_for_status()
        return response.json()

    def confirm_import(self, import_id: str) -> Dict[str, Any]:
        """确认导入
        
        Args:
            import_id: 导入ID
            
        Returns:
            Dict: 确认结果
        """
        response = self.session.post(
            f'{self.base_url}/console/api/apps/import/{import_id}/confirm'
        )
        response.raise_for_status()
        return response.json()

    def check_dependencies(self, app_id: str) -> Dict[str, Any]:
        """检查依赖
        
        Args:
            app_id: 应用ID
            
        Returns:
            Dict: 依赖检查结果
        """
        response = self.session.get(
            f'{self.base_url}/console/api/apps/{app_id}/imports/check-dependencies'
        )
        response.raise_for_status()
        return response.json()
    
    def upload_file(self, file_path, max_retries=3, retry_delay=1):
        """上传文件
        
        Args:
            file_path: 文件路径
            max_retries: 最大重试次数，默认3次
            retry_delay: 重试间隔时间（秒），默认1秒
            
        Returns:
            Dict: 上传文件信息
            
        Raises:
            requests.exceptions.RequestException: 请求异常
            FileNotFoundError: 文件不存在
        """
        url = f"{self.base_url}/console/api/files/upload"

        file_name = os.path.basename(file_path)
        file_ext = os.path.splitext(file_name)[1].lower()

        # 定义文件类型和常见扩展名的双向映射
        type_extension_mapping = {
            'image': {".pg", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"},
            'document': {'.pdf', '.doc', '.docx', '.txt', '.md', 'mdx', '.rtf', '.odt', '.xls', '.xlsx', '.ppt', '.pptx', '.xml', '.csv', '.html', '.eml', '.msg', '.epub'},
            'audio': {".mp3", ".m4a", ".wav", ".webm", ".amr"},
            'video': {".mp4", ".mov", ".mpeg", ".mpga"},
            'custom': set()  # custom类型不做限制
        }
        
        # 创建扩展名到文件类型的反向映射
        extension_type_mapping = {}
        for file_type, extensions in type_extension_mapping.items():
            if file_type != 'custom':
                for ext in extensions:
                    extension_type_mapping[ext] = file_type
        
        file_type = extension_type_mapping.get(file_ext, 'custom')

        mimetype, _ = mimetypes.guess_type(file_path)

        if file_ext == '.xml':
            mimetype = 'text/xml'
            
        if mimetype is None:
            mimetype = 'application/octet-stream'

        # 重试逻辑
        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                with open(file_path, 'rb') as f:
                    multipart_data = MultipartEncoder(
                        fields={
                            'file': (file_name, f, mimetype)
                        }
                    )
                    
                    headers = {
                        'Content-Type': multipart_data.content_type
                    }
                    
                    response = self.session.post(url, data=multipart_data, headers=headers, timeout=30)
                    
                    response.raise_for_status()

                    upload_info = response.json()

                    upload_file_info = {
                        "upload_file": {
                            "type": file_type,
                            "transfer_method": "local_file",
                            "upload_file_id": upload_info['id']
                         }
                    }

                    return upload_file_info
                    
            except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
                last_exception = e
                
                # 如果是最后一次尝试，直接抛出异常
                if attempt == max_retries:
                    break
                    
                # 对于某些错误类型，不进行重试
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    # 4xx 客户端错误通常不需要重试（除了429限流）
                    if 400 <= status_code < 500 and status_code != 429:
                        break
                
                # 等待后重试
                logger.error(f"文件上传失败，第 {attempt + 1} 次尝试，{retry_delay} 秒后重试: {str(e)}")
                time.sleep(retry_delay)
                
                # 指数退避：每次重试增加延迟时间
                retry_delay *= 2
            
            except Exception as e:
                # 对于非网络相关的异常（如文件不存在），直接抛出
                raise e
        
        # 所有重试都失败了，抛出最后一个异常
        if last_exception:
            raise last_exception
        else:
            raise Exception("文件上传失败，原因未知")

    def run_draft_workflow(
        self,
        app_id: str,
        inputs: Dict[str, Any],
        files: Optional[List[Dict]] = None
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """运行草稿工作流
        
        Args:
            app_id: 应用ID
            inputs: 工作流输入参数
            files: 文件列表，可选
            
        Returns:
            Tuple[Dict, List[Dict]]: 工作流执行结果和所有运行结果
            
        Raises:
            requests.exceptions.RequestException: 请求异常
            ValueError: 参数错误
        """
        url = f'{self.base_url}/console/api/apps/{app_id}/workflows/draft/run'
        
        data = {
            'inputs': inputs,
            'files': files if files is not None else [],
        }
        
        try:
            response = self.session.post(
                url,
                json=data,
                stream=False
            )

            response.raise_for_status()
            
            last_result = None
            running_results = []
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    # 跳过不包含 data: 前缀的行
                   
                    if not decoded_line.startswith('data: '):
                        continue

                    result = json.loads(decoded_line.replace('data: ', ''))

                    # print(result)

                    if result['event'] == 'node_finished':
                        last_result = result
                        running_results.append(result)
                    
                    if result['event'] == 'workflow_finished':
                        running_results.append(result)

                        if not last_result['data'].get("error"):
                            last_result = result

            return last_result, running_results
                    
        except requests.exceptions.RequestException as e:
            if e.response is not None:
                if e.response.status_code == 429:
                    raise ValueError("超出调用频率限制")
                error_msg = e.response.json().get('message', str(e))
                raise ValueError(f"请求失败: {error_msg}")
            raise
    
    def run_draft_advanced_chat(
        self,
        app_id: str,
        query: str,
        inputs: Optional[Dict[str, Any]] = None,
        files: Optional[List[Dict]] = None,
        conversation_id: Optional[str] = None,
        parent_message_id: Optional[str] = None
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """运行 AdvancedChat 模式的草稿Chatflow
        
        Args:
            app_id: 应用ID
            query: 用户查询内容（必需）
            inputs: 工作流输入参数，可选
            files: 文件列表，可选
            conversation_id: 会话ID，可选
            parent_message_id: 父消息ID，可选
            
        Returns:
            Tuple[Dict, List[Dict]]: 工作流执行结果和所有运行结果
            
        Raises:
            requests.exceptions.RequestException: 请求异常
            ValueError: 参数错误
        """
        url = f'{self.base_url}/console/api/apps/{app_id}/advanced-chat/workflows/draft/run'
        
        data = {
            'query': query,
            'inputs': inputs if inputs is not None else {},
            'files': files if files is not None else [],
        }

        if conversation_id is not None:
            data['conversation_id'] = conversation_id
        if parent_message_id is not None:
            data['parent_message_id'] = parent_message_id
        
        try:
            response = self.session.post(
                url,
                json=data,
                stream=False
            )

            response.raise_for_status()
            
            last_result = None
            running_results = []
            captured_conversation_id = None

            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    # 跳过不包含 data: 前缀的行
                   
                    if not decoded_line.startswith('data: '):
                        continue

                    result = json.loads(decoded_line.replace('data: ', ''))

                    # print(result)

                    # 捕获 conversation_id，供多轮对话串联使用
                    if result.get('conversation_id'):
                        captured_conversation_id = result['conversation_id']

                    if result['event'] == 'node_finished':
                        last_result = result
                        running_results.append(result)
                    
                    if result['event'] == 'workflow_finished':
                        running_results.append(result)

                        if not last_result['data'].get("error"):
                            last_result = result

            # 确保返回结果携带 conversation_id（多轮对话需用它串联后续轮次）
            if last_result is not None and captured_conversation_id and not last_result.get('conversation_id'):
                last_result['conversation_id'] = captured_conversation_id

            return last_result, running_results
                    
        except requests.exceptions.RequestException as e:
            if e.response is not None:
                if e.response.status_code == 429:
                    raise ValueError("超出调用频率限制")
                error_msg = e.response.json().get('message', str(e))
                raise ValueError(f"请求失败: {error_msg}")
            raise


