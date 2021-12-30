"""
Load secrets from an AWS secret manager

Author  : Preocts <Preocts#8196>
Git Repo: https://github.com/Preocts/secretbox
"""
import json
import logging
import os
from typing import Any
from typing import Dict
from typing import Optional

try:
    import boto3
    from botocore.exceptions import ClientError
    from botocore.exceptions import NoCredentialsError
    from mypy_boto3_secretsmanager.client import SecretsManagerClient
except ImportError:
    boto3 = None
    SecretsManagerClient = None

from secretbox.loader import Loader

FILTER_SECRETS = True


class AWSSecretLoader(Loader):
    """Load secrets from an AWS secret manager"""

    logger = logging.getLogger(__name__)

    def __init__(self) -> None:
        super().__init__()
        self.aws_sstore: Optional[str] = None
        self.aws_region: Optional[str] = None

    def populate_region_store_names(self, **kwargs: Any) -> None:
        """Populates store/region name"""
        kw_sstore = kwargs.get("aws_sstore_name")
        kw_region = kwargs.get("aws_region_name")
        os_sstore = os.getenv("AWS_SSTORE_NAME")
        os_region = os.getenv("AWS_REGION_NAME", os.getenv("AWS_REGION"))  # Lambda's

        # Use the keyword over the os, default to None
        self.aws_sstore = kw_sstore if kw_sstore is not None else os_sstore
        self.aws_region = kw_region if kw_region is not None else os_region

    def load_values(self, **kwargs: Any) -> bool:
        """
        Load all secrets from AWS secret store
        Requires `aws_sstore_name` and `aws_region_name` keywords to be
        provided or for those values to be in the environment variables
        under `AWS_SSTORE_NAME` and `AWS_REGION_NAME`.

        `aws_sstore_name` is the name of the store, not the arn.
        """
        if boto3 is None:
            self.logger.error("Required boto3 modules missing, can't load AWS secrets")
            return False

        self.populate_region_store_names(**kwargs)
        if self.aws_sstore is None:
            self.logger.error("Missing secret store name")
            return False

        aws_client = self.connect_aws_client()
        if aws_client is None:
            self.logger.error("Invalid secrets manager client")
            return False

        secrets: Dict[str, str] = {}
        try:
            logging.getLogger("botocore.parsers").addFilter(self.secrets_filter)
            response = aws_client.get_secret_value(SecretId=self.aws_sstore)

        except NoCredentialsError as err:
            self.logger.error("Missing AWS credentials (%s)", err)

        except ClientError as err:
            self._log_client_error(err)

        else:
            self.logger.debug("Found %s values from AWS.", len(secrets))
            secrets = json.loads(response.get("SecretString", "{}"))
            self.loaded_values.update(secrets)

        finally:
            logging.getLogger("botocore.parsers").removeFilter(self.secrets_filter)

        return bool(secrets)

    def connect_aws_client(self) -> Optional[SecretsManagerClient]:
        """Make connection"""
        # Define client here for type hinting
        client: Optional[SecretsManagerClient] = None
        session = boto3.session.Session()

        if not self.aws_region:
            self.logger.debug("No valid AWS region, cannot create client.")
            return None

        else:
            try:
                client = session.client(
                    service_name="secretsmanager",
                    region_name=self.aws_region,
                )
                return client
            except ClientError as err:
                self._log_client_error(err)
                return None

    def _log_client_error(self, err: ClientError) -> None:
        """Internal: reusable logging"""
        self.logger.error(
            "%s - %s (%s)",
            err.response["Error"]["Code"],
            err.response["Error"]["Message"],
            err.response["ResponseMetadata"],
        )

    @staticmethod
    def secrets_filter(record: logging.LogRecord) -> bool:
        """
        Hide botocore.parsers responses which include decrypted secrets

        https://github.com/boto/botocore/issues/1211#issuecomment-327799341
        """
        if record.levelno > logging.DEBUG or not FILTER_SECRETS:
            return True
        if "body" in record.msg or "headers" in record.msg:
            if isinstance(record.args, dict):
                record.args = {key: "REDACTED" for key in record.args}
            else:
                record.args = ("REDACTED",) * len(record.args or [])
        return True
