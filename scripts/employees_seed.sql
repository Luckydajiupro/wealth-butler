-- ============================================================
-- 补充数据种子脚本 - 员工数据
-- ============================================================

USE wealth_butler;
SET FOREIGN_KEY_CHECKS=0;

-- 员工数据 (20条)
INSERT INTO `base_user` (`id`, `username`, `email`, `phone`, `password_hash`, `source_module`, `status`, `user_type`, `employee_role`, `advisor_level`, `extra_data`) VALUES
(201, 'employee001', 'employee001@xxtech.com', '13812345001', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '理财顾问', '高级', '{"real_name": "王明", "city": "北京", "department": "投顾部"}'),
(202, 'employee002', 'employee002@xxtech.com', '13812345002', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '理财顾问', '中级', '{"real_name": "李芳", "city": "上海", "department": "投顾部"}'),
(203, 'employee003', 'employee003@xxtech.com', '13812345003', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '理财顾问', '初级', '{"real_name": "张静", "city": "深圳", "department": "投顾部"}'),
(204, 'employee004', 'employee004@xxtech.com', '13812345004', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '理财顾问', '中级', '{"real_name": "刘强", "city": "广州", "department": "投顾部"}'),
(205, 'employee005', 'employee005@xxtech.com', '13812345005', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '理财顾问', '高级', '{"real_name": "陈磊", "city": "杭州", "department": "投顾部"}'),
(206, 'employee006', 'employee006@xxtech.com', '13812345006', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '风控专员', NULL, '{"real_name": "杨洋", "city": "北京", "department": "风控部"}'),
(207, 'employee007', 'employee007@xxtech.com', '13812345007', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '风控专员', NULL, '{"real_name": "黄勇", "city": "上海", "department": "风控部"}'),
(208, 'employee008', 'employee008@xxtech.com', '13812345008', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '风控专员', NULL, '{"real_name": "赵艳", "city": "深圳", "department": "风控部"}'),
(209, 'employee009', 'employee009@xxtech.com', '13812345009', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '客户经理', NULL, '{"real_name": "周杰", "city": "广州", "department": "客服部"}'),
(210, 'employee010', 'employee010@xxtech.com', '13812345010', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '客户经理', NULL, '{"real_name": "吴涛", "city": "成都", "department": "客服部"}'),
(211, 'employee011', 'employee011@xxtech.com', '13812345011', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '客户经理', NULL, '{"real_name": "徐华", "city": "重庆", "department": "客服部"}'),
(212, 'employee012', 'employee012@xxtech.com', '13812345012', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '客户经理', NULL, '{"real_name": "孙霞", "city": "南京", "department": "客服部"}'),
(213, 'employee013', 'employee013@xxtech.com', '13812345013', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '客户经理', NULL, '{"real_name": "朱平", "city": "杭州", "department": "客服部"}'),
(214, 'employee014', 'employee014@xxtech.com', '13812345014', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '业务管理员', NULL, '{"real_name": "马刚", "city": "北京", "department": "运营部"}'),
(215, 'employee015', 'employee015@xxtech.com', '13812345015', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '业务管理员', NULL, '{"real_name": "胡伟", "city": "上海", "department": "运营部"}'),
(216, 'employee016', 'employee016@xxtech.com', '13812345016', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '理财顾问', '初级', '{"real_name": "郭芳", "city": "深圳", "department": "投顾部"}'),
(217, 'employee017', 'employee017@xxtech.com', '13812345017', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '理财顾问', '中级', '{"real_name": "林娜", "city": "广州", "department": "投顾部"}'),
(218, 'employee018', 'employee018@xxtech.com', '13812345018', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '风控专员', NULL, '{"real_name": "何秀", "city": "成都", "department": "风控部"}'),
(219, 'employee019', 'employee019@xxtech.com', '13812345019', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '客户经理', NULL, '{"real_name": "高敏", "city": "重庆", "department": "客服部"}'),
(220, 'employee020', 'employee020@xxtech.com', '13812345020', '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG', 'WealthButler', 'active', 'EMPLOYEE', '业务管理员', NULL, '{"real_name": "梁静", "city": "南京", "department": "运营部"}');

SET FOREIGN_KEY_CHECKS=1;
-- 完成
