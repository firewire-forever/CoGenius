import openstack
import openstack.exceptions
from flask import current_app

class OpenStackService:
    _instance = None
    _conn = None
    # Add attributes to cache the data
    image_constraints_prompt = None
    external_network_name = None
    external_network_id = None  # UUID for Terraform

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(OpenStackService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._conn is None:
            self._connect()

    def _connect(self):
        """Establishes a connection to the OpenStack cloud."""
        try:
            auth_params = {
                "auth_url": current_app.config.get("OPENSTACK_URL"),
                "project_name": current_app.config.get("OPENSTACK_TENANT_NAME"),
                "username": current_app.config.get("OPENSTACK_USER"),
                "password": current_app.config.get("OPENSTACK_PASSWORD"),
                "user_domain_name": current_app.config.get("OPENSTACK_DOMAIN"),
                "project_domain_name": current_app.config.get("OPENSTACK_DOMAIN")
            }
            
            # Log parameters for debugging, except for the password
            log_params = {k: v for k, v in auth_params.items() if k != 'password'}
            current_app.logger.info(f"Attempting to connect to OpenStack with parameters: {log_params}")

            self._conn = openstack.connect(**auth_params)
            
            # The connect call itself can be lazy. Perform a read-only operation to ensure connection is valid.
            # Listing projects is a safe way to verify authentication and authorization.
            projects = list(self._conn.identity.projects())
            project_names = [p.name for p in projects]

            if auth_params["project_name"] not in project_names:
                raise openstack.exceptions.SDKException(f"Project '{auth_params['project_name']}' not found in user's accessible projects: {project_names}")

            current_app.logger.info("Successfully connected to OpenStack and verified project access.")
        except openstack.exceptions.SDKException as e:
            current_app.logger.error(f"Failed to connect or verify project in OpenStack: {e}")
            self._conn = None
        except Exception as e:
            current_app.logger.error(f"An unexpected error occurred during OpenStack connection: {e}")
            self._conn = None
            
    def initialize_data(self):
        """
        Connects to OpenStack and fetches all necessary data once, then caches it.
        This should be called at application startup.
        """
        if self._conn is None:
            current_app.logger.error("Cannot initialize OpenStack data, connection not established.")
            # Set fallback data
            self.image_constraints_prompt = "无法连接到OpenStack平台，无法获取实时镜像约束。"
            self.external_network_name = current_app.config.get('PUBLIC_NET_NAME') or 'public'
            self.external_network_id = current_app.config.get('PUBLIC_NET_ID') or 'public'
            return

        current_app.logger.info("Initializing and caching OpenStack data (images, networks)...")
        # Fetch and cache image constraints
        try:
            images = self._conn.image.images()
            image_details = [f"- **{img.name}**: 最小磁盘要求: {img.min_disk}GB" for img in images]
            if not image_details:
                self.image_constraints_prompt = "在OpenStack平台上未找到任何可用镜像。"
            else:
                self.image_constraints_prompt = f"""3.  **平台约束 (必须严格遵守)**:
    -   **通用磁盘约束**: 不同的操作系统镜像需要不同的最小磁盘空间。在定义 `disk` 属性时，其大小**必须大于或等于**所选镜像的最小磁盘要求。例如，如果选择 `ubuntu20`，其最小要求是 20GB，则 `disk` 必须 `larger than 19GB` 或 `equal to 20GB` 或更大。
    -   **可用操作系统镜像及要求**: 你**必须**从以下列表中选择最合适的操作系统。如果案例中提到的OS不在列表中，请选择功能上最接近的一个。
        ```
        {chr(10).join(image_details)}
        ```
"""
        except Exception as e:
            current_app.logger.error(f"Failed to fetch and cache images: {e}")
            self.image_constraints_prompt = f"从OpenStack获取镜像列表时出错: {e}"

        # Fetch and cache external network name and UUID
        try:
            external_networks = list(self._conn.network.networks(**{'router:external': True}))
            if not external_networks:
                current_app.logger.warning("No external network found. Falling back to default 'public'.")
                self.external_network_name = 'public'
                self.external_network_id = 'public'  # Will likely fail, but fallback
            else:
                if len(external_networks) > 1:
                    network_names = [net.name for net in external_networks]
                    current_app.logger.warning(f"Multiple external networks found: {network_names}. Using the first one: '{external_networks[0].name}'.")
                self.external_network_name = external_networks[0].name
                self.external_network_id = external_networks[0].id  # Store UUID for Terraform
                current_app.logger.info(f"External network: name='{self.external_network_name}', id='{self.external_network_id}'")
        except Exception as e:
            current_app.logger.error(f"Failed to fetch and cache external network: {e}")
            self.external_network_name = current_app.config.get('PUBLIC_NET_NAME') or 'public'
            self.external_network_id = current_app.config.get('PUBLIC_NET_ID') or 'public'

        current_app.logger.info(f"OpenStack data cached successfully. External network: '{self.external_network_name}'.")

    def get_image_constraints(self) -> str:
        """
        Returns the cached image constraints prompt.
        """
        return self.image_constraints_prompt

    def get_external_network_name(self) -> str:
        """
        Returns the cached name of the external network.
        """
        return self.external_network_name

    def get_external_network_id(self) -> str:
        """
        Returns the cached UUID of the external network for Terraform.
        """
        return self.external_network_id

def get_openstack_service():
    """Factory function to get the singleton instance of the OpenStack service."""
    return OpenStackService() 
