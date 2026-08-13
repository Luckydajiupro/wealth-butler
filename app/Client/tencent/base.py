from qcloud_cos import CosConfig
from qcloud_cos import CosS3Client

from Base.Config.setting import settings

# https://cloud.tencent.com/document/product/460/72998
# 1. 设置用户属性, 包括 secret_id, secret_key, region 等。Appid 已在 CosConfig 中移除，请在参数 Bucket 中带上 Appid。Bucket 由 BucketName-Appid 组成
secret_id = settings.tencent_cos.secret_id    # 替换为用户的 SecretId，请登录访问管理控制台进行查看和管理，https://console.cloud.tencent.com/cam/capi
secret_key = settings.tencent_cos.secret_key  # 替换为用户的 SecretKey，请登录访问管理控制台进行查看和管理，https://console.cloud.tencent.com/cam/capi
region = settings.tencent_cos.region     # 替换为用户的 region，已创建桶归属的 region 可以在控制台查看，https://console.cloud.tencent.com/cos5/bucket
                           # COS支持的所有 region 列表参见 https://cloud.tencent.com/document/product/436/6224
token = None               # 如果使用永久密钥不需要填入token，如果使用临时密钥需要填入，临时密钥生成和使用指引参见 https://cloud.tencent.com/document/product/436/14048
scheme = settings.tencent_cos.scheme          # 指定使用 http/https 协议来访问 COS，默认为 https，可不填


endpoint = 'cos.accelerate.myqcloud.com' # 替换为用户的 endpoint 或者 cos 全局加速域名，如果使用桶的全球加速域名，需要先开启桶的全球加速功能，请参见 https://cloud.tencent.com/document/product/436/38864


config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token, Scheme=scheme)
tencent_code3_client = CosS3Client(config)