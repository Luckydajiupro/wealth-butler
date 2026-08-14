import os

from Base.Client.tencent.base import tencent_code3_client


def ci_auditing_text_submit(text: str):

    response = tencent_code3_client.ci_auditing_text_submit(
        Bucket=os.getenv("TC_BUCKET_NAME"),  # 桶名称
        Content=text.encode("utf-8"),  # 需要审核的文本内容
        BizType='',  # 表示审核策略的唯一标识
    )
    return response


def is_normal(response: dict) -> bool:
    """
    判断文本是否合规
    :param response:
    :return:
    """
    if response.get('JobsDetail').get("Label") == "Normal":
        return True
    else:
        return False


if __name__ == '__main__':
    print(is_normal(ci_auditing_text_submit("你好")))
    print("\n")
    print(is_normal(ci_auditing_text_submit("你好,草你妈啊")))
