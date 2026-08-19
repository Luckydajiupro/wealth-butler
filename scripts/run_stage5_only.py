"""
单独执行阶段5：MinIO合规证据元数据生成
用于测试和修复阶段5的数据生成问题
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
from datetime import datetime
from app.Base.Client.mysqlClient import MySQLClient
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_stage5():
    """执行阶段5: 生成MinIO对象存储元数据"""

    logger.info("=" * 60)
    logger.info("阶段5: 开始生成MinIO对象存储元数据")
    logger.info("=" * 60)

    mysql_conn = MySQLClient()

    try:
        # 读取已有数据
        logger.info("读取交易数据...")
        transactions = mysql_conn.execute_sync("""
            SELECT id, customer_id, product_id, transaction_type, employee_id, transaction_time, created_at
            FROM fin_transaction
            WHERE transaction_type = '申购'
            ORDER BY id
            LIMIT 100
        """)
        logger.info(f"找到 {len(transactions)} 笔申购交易")

        logger.info("读取客户数据...")
        customers = mysql_conn.execute_sync("""
            SELECT id FROM base_user
            WHERE user_type = 'customer'
            ORDER BY id
            LIMIT 150
        """)
        logger.info(f"找到 {len(customers)} 个客户")

        logger.info("读取风险评估数据...")
        risk_assessments = mysql_conn.execute_sync("""
            SELECT id, customer_id, assessment_time
            FROM fin_risk_assessment
            ORDER BY id
            LIMIT 100
        """)
        logger.info(f"找到 {len(risk_assessments)} 条风险评估")

        evidence_count = 0

        # 为申购交易生成录音录像元数据
        logger.info("生成交易录音录像证据...")
        for trans in transactions:
            # 录音文件
            audio_path = f"compliance/recordings/{trans['customer_id']}/{datetime.now().strftime('%Y%m')}/audio_{trans['id']}.mp3"
            event_id = f"evt_audio_{trans['id']}_{int(datetime.now().timestamp()*1000)}"
            evidence_id = f"evd_trans_{trans['id']}_audio"
            sql = """
                INSERT INTO biz_compliance_evidence
                (event_id, evidence_id, action, customer_id, product_id, evidence_type,
                 artifact_uri, completed_at, verified_by, verification_method, trace_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """
            params = (
                event_id,
                evidence_id,
                'ISSUED',
                trans['customer_id'],
                trans.get('product_id'),
                '录音录像',
                audio_path,
                trans['created_at'],
                trans['employee_id'],
                'system_auto',
                f"trace_{trans['id']}",
            )
            mysql_conn.execute_sync(sql, params)
            evidence_count += 1

            # 30%概率有视频
            if random.random() < 0.3:
                video_path = f"compliance/recordings/{trans['customer_id']}/{datetime.now().strftime('%Y%m')}/video_{trans['id']}.mp4"
                event_id_video = f"evt_video_{trans['id']}_{int(datetime.now().timestamp()*1000)}"
                evidence_id_video = f"evd_trans_{trans['id']}_video"
                params = (
                    event_id_video,
                    evidence_id_video,
                    'ISSUED',
                    trans['customer_id'],
                    trans.get('product_id'),
                    '录音录像',
                    video_path,
                    trans['created_at'],
                    trans['employee_id'],
                    'system_auto',
                    f"trace_{trans['id']}",
                )
                mysql_conn.execute_sync(sql, params)
                evidence_count += 1

        # 为客户生成风险揭示书元数据
        logger.info("生成客户风险揭示书证据...")
        for customer in customers:
            disclosure_path = f"compliance/disclosures/{customer['id']}/risk_disclosure_{datetime.now().strftime('%Y%m%d')}.pdf"
            event_id = f"evt_disclosure_{customer['id']}_{int(datetime.now().timestamp()*1000)}"
            evidence_id = f"evd_customer_{customer['id']}_disclosure"
            sql = """
                INSERT INTO biz_compliance_evidence
                (event_id, evidence_id, action, customer_id, product_id, evidence_type,
                 artifact_uri, completed_at, verified_by, verification_method, trace_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """
            # 获取该客户的投顾ID
            employee_id = 1  # 默认投顾
            customer_trans = mysql_conn.execute_sync(
                "SELECT employee_id FROM fin_transaction WHERE customer_id = %s LIMIT 1",
                (customer['id'],)
            )
            if customer_trans:
                employee_id = customer_trans[0]['employee_id']

            params = (
                event_id,
                evidence_id,
                'ISSUED',
                customer['id'],
                None,  # product_id为空，因为这是客户级证据
                '风险揭示书',
                disclosure_path,
                datetime.now(),
                employee_id,
                'manual_upload',
                f"trace_customer_{customer['id']}",
            )
            mysql_conn.execute_sync(sql, params)
            evidence_count += 1

        # 为风险评估生成问卷存档
        logger.info("生成风险评估问卷证据...")
        for assessment in risk_assessments:
            questionnaire_path = f"compliance/assessments/{assessment['customer_id']}/questionnaire_{assessment['id']}.pdf"
            event_id = f"evt_assessment_{assessment['id']}_{int(datetime.now().timestamp()*1000)}"
            evidence_id = f"evd_assessment_{assessment['id']}_questionnaire"
            sql = """
                INSERT INTO biz_compliance_evidence
                (event_id, evidence_id, action, customer_id, product_id, evidence_type,
                 artifact_uri, completed_at, verified_by, verification_method, trace_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """
            params = (
                event_id,
                evidence_id,
                'ISSUED',
                assessment['customer_id'],
                None,  # product_id为空，风险评估是客户级的
                '风险评估问卷',
                questionnaire_path,
                assessment['assessment_time'],
                1,  # 默认投顾ID
                'system_auto',
                f"trace_assessment_{assessment['id']}",
            )
            mysql_conn.execute_sync(sql, params)
            evidence_count += 1

        logger.info(f"✅ 阶段5完成: 生成{evidence_count}条MinIO元数据索引")

        # 验证数据
        logger.info("\n" + "=" * 60)
        logger.info("验证插入的数据...")
        logger.info("=" * 60)

        total_count = mysql_conn.execute_sync("SELECT COUNT(*) as cnt FROM biz_compliance_evidence")
        logger.info(f"合规证据总记录数: {total_count[0]['cnt']}")

        by_type = mysql_conn.execute_sync("""
            SELECT evidence_type, COUNT(*) as cnt
            FROM biz_compliance_evidence
            GROUP BY evidence_type
        """)
        logger.info("按证据类型统计:")
        for row in by_type:
            logger.info(f"  - {row['evidence_type']}: {row['cnt']} 条")

        sample = mysql_conn.execute_sync("""
            SELECT event_id, evidence_id, action, customer_id, evidence_type, artifact_uri
            FROM biz_compliance_evidence
            ORDER BY id DESC
            LIMIT 5
        """)
        logger.info("\n最新5条记录样本:")
        for row in sample:
            logger.info(f"  {row['evidence_type']:10} | customer_id={row['customer_id']:4} | {row['artifact_uri'][:50]}")

        logger.info("\n✅ 阶段5执行成功！")

    except Exception as e:
        logger.error(f"❌ 阶段5执行失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True

if __name__ == "__main__":
    success = run_stage5()
    sys.exit(0 if success else 1)
