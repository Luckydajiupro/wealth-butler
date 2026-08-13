from Base.Repository.models.moduleDbModel import BaseModuleDBModel
from typing import Optional

class Student(BaseModuleDBModel):
    table_alias = "test_student"
    create_table_sql = f"""
    CREATE TABLE `{table_alias}` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `name` VARCHAR(50) NOT NULL COMMENT '姓名',
  `age` TINYINT UNSIGNED COMMENT '年龄',
  `gender` ENUM('男', '女', '未知') DEFAULT '未知' COMMENT '性别',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生信息表';
    """

    id: Optional[int] = None
    name: str
    age: int
    gender: str = '未知'


    def select_by_name(self,name: str):
        sql = f"""Select * from {self.table_alias} where name like '%{name}%'"""

        return Student.get_db_connection().execute(sql=sql)






if __name__ == '__main__':
    stu_1 = Student(name='张三',age=15)
    stu_1.save()
    stu_1.get_all()
    list = stu_1.select_by_name(name='张')
    print(list)