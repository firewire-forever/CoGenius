"""
Software Registry - Query Logic
查询软件安装知识的逻辑
"""

import os
import yaml
from typing import Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum


class InstallType(Enum):
    """软件安装类型"""
    APT = "apt"           # 标准 apt 包
    SCRIPT = "script"     # 需要执行脚本安装
    MANUAL = "manual"     # 需要手动安装
    PIP = "pip"           # Python pip 安装


@dataclass
class SoftwareInfo:
    """软件信息数据类"""
    name: str
    install_type: InstallType
    package: Optional[str] = None
    verify_cmd: Optional[str] = None
    install_script: Optional[str] = None
    dependencies: Optional[list] = None
    offline_available: bool = True
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'install_type': self.install_type.value,
            'package': self.package,
            'verify_cmd': self.verify_cmd,
            'install_script': self.install_script,
            'dependencies': self.dependencies,
            'offline_available': self.offline_available,
            'note': self.note
        }


class SoftwareRegistry:
    """
    软件安装知识库查询器

    使用方法:
        registry = SoftwareRegistry()
        info = registry.lookup("nginx")
        print(info.package)  # nginx
        print(info.verify_cmd)  # nginx -v
    """

    def __init__(self, knowledge_base_path: Optional[str] = None):
        """
        初始化知识库

        Args:
            knowledge_base_path: 知识库 YAML 文件路径，默认使用同目录下的 knowledge_base.yaml
        """
        if knowledge_base_path is None:
            # 默认路径：同目录下的 knowledge_base.yaml
            current_dir = os.path.dirname(os.path.abspath(__file__))
            knowledge_base_path = os.path.join(current_dir, 'knowledge_base.yaml')

        self.knowledge_base_path = knowledge_base_path
        self._knowledge_base: Dict[str, Any] = {}
        self._load_knowledge_base()

    def _load_knowledge_base(self) -> None:
        """加载知识库文件"""
        try:
            with open(self.knowledge_base_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                self._knowledge_base = data.get('software', {})
        except FileNotFoundError:
            raise FileNotFoundError(f"Knowledge base file not found: {self.knowledge_base_path}")
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in knowledge base: {e}")

    def lookup(self, software_name: str, version: Optional[str] = None) -> Optional[SoftwareInfo]:
        """
        查询软件安装信息

        Args:
            software_name: 软件名称（不区分大小写）
            version: 可选的版本号

        Returns:
            SoftwareInfo 对象，如果未找到返回 None
        """
        # 标准化名称（小写）
        normalized_name = software_name.lower().strip()

        # 直接查找
        if normalized_name in self._knowledge_base:
            return self._parse_software_info(normalized_name, self._knowledge_base[normalized_name])

        # 尝试带版本查找（如 openjdk-11-jdk）
        if version:
            versioned_name = f"{normalized_name}-{version}"
            if versioned_name in self._knowledge_base:
                return self._parse_software_info(versioned_name, self._knowledge_base[versioned_name])

        return None

    def _parse_software_info(self, name: str, data: Dict[str, Any]) -> SoftwareInfo:
        """解析软件信息"""
        install_type = InstallType(data.get('type', 'apt'))

        return SoftwareInfo(
            name=name,
            install_type=install_type,
            package=data.get('package'),
            verify_cmd=data.get('verify_cmd'),
            install_script=data.get('install_script'),
            dependencies=data.get('dependencies'),
            offline_available=data.get('offline_available', True),
            note=data.get('note')
        )

    def get_install_info(self, software_name: str, version: Optional[str] = None) -> Dict[str, Any]:
        """
        获取软件安装信息（用于 Ansible 生成）

        Args:
            software_name: 软件名称
            version: 可选版本号

        Returns:
            包含安装信息的字典
        """
        info = self.lookup(software_name, version)

        if info is None:
            # 未在知识库中找到，返回基本信息
            return {
                'found': False,
                'name': software_name,
                'package': software_name.lower(),
                'install_type': 'apt',  # 默认尝试 apt
                'verify_cmd': f"which {software_name.lower()}",
                'offline_available': True,
                'needs_llm_generation': True
            }

        result = info.to_dict()
        result['found'] = True
        result['needs_llm_generation'] = False

        return result

    def list_all_software(self) -> list:
        """列出知识库中所有软件名称"""
        return list(self._knowledge_base.keys())

    def is_offline_available(self, software_name: str) -> bool:
        """检查软件是否可以在离线环境安装"""
        info = self.lookup(software_name)
        return info.offline_available if info else True

    def get_dependencies(self, software_name: str) -> list:
        """获取软件的依赖列表"""
        info = self.lookup(software_name)
        return info.dependencies if info and info.dependencies else []