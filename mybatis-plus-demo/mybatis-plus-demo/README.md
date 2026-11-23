# MyBatis-Plus 示例工程

这是一个完整的 MyBatis-Plus 示例项目，演示了 MyBatis-Plus 的核心功能和最佳实践。

## 项目简介

本项目基于 Spring Boot 3.5.3 和 MyBatis-Plus 3.5.5，使用 Java 21 开发，展示了 MyBatis-Plus 的各种特性：

- **基础 CRUD 操作**：继承 BaseMapper 和 IService 获得强大的单表操作能力
- **条件构造器**：类型安全的查询条件构建
- **分页查询**：内置分页插件，支持多种数据库
- **代码生成器**：自动生成 Entity、Mapper、Service、Controller
- **乐观锁**：防止并发更新冲突
- **逻辑删除**：数据安全删除，不物理删除数据
- **自动填充**：创建时间、更新时间等字段自动填充
- **多数据源**：支持主从分离、读写分离

## 技术栈

- **Java**: 21
- **Spring Boot**: 3.5.3
- **MyBatis-Plus**: 3.5.5
- **数据库**: MySQL 8.0+（生产环境）/ H2（测试环境）
- **构建工具**: Maven 3.9+
- **其他依赖**:
  - Lombok：简化实体类代码
  - Spring Boot DevTools：热重载
  - Spring Boot Validation：参数校验
  - SpringDoc OpenAPI：API 文档生成

## 项目结构

```
mybatis-plus-demo/
├── src/
│   ├── main/
│   │   ├── java/com/example/mybatisplus/
│   │   │   ├── MybatisPlusDemoApplication.java    # 启动类
│   │   │   ├── config/
│   │   │   │   ├── MybatisPlusConfig.java         # MyBatis-Plus配置
│   │   │   │   └── MyMetaObjectHandler.java       # 自动填充处理器
│   │   │   ├── controller/
│   │   │   │   └── UserController.java            # 用户控制器
│   │   │   ├── entity/
│   │   │   │   └── User.java                      # 用户实体类
│   │   │   ├── mapper/
│   │   │   │   └── UserMapper.java                # 用户Mapper接口
│   │   │   ├── service/
│   │   │   │   ├── UserService.java               # 用户服务接口
│   │   │   │   └── impl/
│   │   │   │       └── UserServiceImpl.java       # 用户服务实现
│   │   │   └── generator/
│   │   │       └── CodeGenerator.java             # 代码生成器
│   │   └── resources/
│   │       ├── application.yml                    # 应用配置
│   │       ├── mapper/
│   │       │   └── UserMapper.xml                 # Mapper XML文件
│   │       └── sql/
│   │           ├── init.sql                       # 完整初始化脚本
│   │           └── user_table.sql                 # 简化建表脚本
│   └── test/
│       ├── java/
│       │   └── com/example/mybatisplus/
│       │       └── MybatisPlusDemoApplicationTests.java  # 测试类
│       └── resources/
│           ├── application-test.yml               # 测试配置
│           └── sql/
│               ├── test-schema.sql                # 测试建表脚本
│               └── test-data.sql                  # 测试数据脚本
├── pom.xml                                        # Maven配置
└── README.md                                      # 项目说明
```

## 快速开始

### 1. 环境要求

- JDK 21+
- Maven 3.9+
- MySQL 8.0+（生产环境）

### 2. 数据库准备

#### 创建数据库
```sql
CREATE DATABASE mybatis_plus_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

#### 执行初始化脚本
```bash
# 方式1：使用完整脚本（推荐）
mysql -u root -p mybatis_plus_demo < src/main/resources/sql/init.sql

# 方式2：使用简化脚本
mysql -u root -p mybatis_plus_demo < src/main/resources/sql/user_table.sql
```

### 3. 配置数据库连接

修改 `src/main/resources/application.yml` 中的数据库连接信息：

```yaml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/mybatis_plus_demo?useUnicode=true&characterEncoding=utf8&useSSL=false&serverTimezone=Asia/Shanghai
    username: your_username
    password: your_password
```

### 4. 运行项目

```bash
# 编译项目
mvn clean compile

# 运行项目
mvn spring-boot:run

# 或者运行主类
java -jar target/mybatis-plus-demo-1.0.0.jar
```

### 5. 访问应用

- **应用首页**: http://localhost:8080
- **API 文档**: http://localhost:8080/swagger-ui.html
- **H2 控制台**（测试环境）: http://localhost:8080/h2-console

## 核心功能演示

### 1. 基础 CRUD 操作

```java
// 插入
User user = new User("张三", 25, "zhangsan@example.com");
userService.save(user);

// 查询
User foundUser = userService.getById(1L);
List<User> allUsers = userService.list();

// 更新
user.setAge(26);
userService.updateById(user);

// 删除（逻辑删除）
userService.removeById(1L);
```

### 2. 条件构造器

```java
// Lambda 查询
LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();
wrapper.like(User::getName, "张")
       .between(User::getAge, 20, 30)
       .orderByDesc(User::getCreateTime);
List<User> users = userMapper.selectList(wrapper);

// 复杂条件
wrapper.like(User::getName, "张")
       .or()
       .between(User::getAge, 25, 35)
       .and(w -> w.like(User::getEmail, "example")
                  .or()
                  .like(User::getEmail, "test"));
```

### 3. 分页查询

```java
// 基础分页
Page<User> page = new Page<>(1, 10); // 第1页，每页10条
IPage<User> userPage = userMapper.selectPage(page, null);

// 带条件分页
LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();
wrapper.ge(User::getAge, 18);
IPage<User> adultPage = userMapper.selectPage(page, wrapper);
```

### 4. 批量操作

```java
// 批量插入
List<User> users = Arrays.asList(
    new User("用户1", 20, "user1@test.com"),
    new User("用户2", 21, "user2@test.com")
);
userService.saveBatch(users);

// 批量更新
userService.updateBatchById(users);

// 批量删除
List<Long> ids = Arrays.asList(1L, 2L, 3L);
userService.removeByIds(ids);
```

## API 接口说明

### 用户管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/users` | 获取所有用户 |
| GET | `/api/users/{id}` | 根据ID获取用户 |
| POST | `/api/users` | 创建用户 |
| PUT | `/api/users/{id}` | 更新用户 |
| DELETE | `/api/users/{id}` | 删除用户 |
| GET | `/api/users/page` | 分页查询用户 |
| GET | `/api/users/age-range` | 按年龄范围查询 |
| GET | `/api/users/search` | 按姓名模糊查询 |
| GET | `/api/users/email-domain` | 按邮箱域名查询 |
| GET | `/api/users/complex-query` | 复杂条件查询 |
| GET | `/api/users/age-statistics` | 年龄段统计 |
| POST | `/api/users/batch` | 批量创建用户 |
| PUT | `/api/users/batch-age` | 批量更新年龄 |
| PUT | `/api/users/{id}/optimistic` | 乐观锁更新 |
| GET | `/api/users/count` | 获取用户总数 |

## 测试

### 运行单元测试

```bash
# 运行所有测试
mvn test

# 运行特定测试类
mvn test -Dtest=MybatisPlusDemoApplicationTests

# 运行特定测试方法
mvn test -Dtest=MybatisPlusDemoApplicationTests#testBasicCRUD
```

### 测试覆盖的功能

- ✅ 基础 CRUD 操作
- ✅ 条件构造器（QueryWrapper、LambdaQueryWrapper）
- ✅ 分页查询
- ✅ 批量操作
- ✅ 乐观锁
- ✅ 逻辑删除
- ✅ 自动填充
- ✅ 自定义 SQL
- ✅ 统计功能

## 代码生成器使用

运行 `CodeGenerator.java` 可以自动生成代码：

```java
public static void main(String[] args) {
    CodeGenerator generator = new CodeGenerator();
    // 生成指定表的代码
    generator.generateByTables("user", "order", "product");
}
```

生成的代码包括：
- Entity 实体类（包含 MyBatis-Plus 注解）
- Mapper 接口和 XML 文件
- Service 接口和实现类
- Controller 控制器（REST 风格）

## 配置说明

### MyBatis-Plus 核心配置

```yaml
mybatis-plus:
  # Mapper XML 文件位置
  mapper-locations: classpath*:/mapper/**/*.xml
  # 实体类包路径
  type-aliases-package: com.example.mybatisplus.entity
  
  global-config:
    db-config:
      # 主键类型
      id-type: ASSIGN_ID
      # 逻辑删除
      logic-delete-field: deleted
      logic-delete-value: 1
      logic-not-delete-value: 0
      # 字段填充策略
      insert-strategy: NOT_NULL
      update-strategy: NOT_NULL
```

### 插件配置

```java
@Configuration
public class MybatisPlusConfig {
    
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        
        // 分页插件
        PaginationInnerInterceptor paginationInterceptor = 
            new PaginationInnerInterceptor(DbType.MYSQL);
        interceptor.addInnerInterceptor(paginationInterceptor);
        
        // 乐观锁插件
        interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());
        
        return interceptor;
    }
}
```

## 常见问题

### Q1: 如何启用逻辑删除？

A: 在实体类字段上添加 `@TableLogic` 注解：

```java
@TableLogic
private Integer deleted;
```

### Q2: 如何实现自动填充？

A: 实现 `MetaObjectHandler` 接口：

```java
@Component
public class MyMetaObjectHandler implements MetaObjectHandler {
    @Override
    public void insertFill(MetaObject metaObject) {
        this.strictInsertFill(metaObject, "createTime", LocalDateTime.class, LocalDateTime.now());
    }
    
    @Override
    public void updateFill(MetaObject metaObject) {
        this.strictUpdateFill(metaObject, "updateTime", LocalDateTime.class, LocalDateTime.now());
    }
}
```

### Q3: 如何使用乐观锁？

A: 在实体类版本字段上添加 `@Version` 注解：

```java
@Version
private Integer version;
```

### Q4: 分页查询总数为0？

A: 检查是否配置了分页插件，确保 SQL 语句正确。

### Q5: 逻辑删除不生效？

A: 检查全局配置和实体类注解，确保字段名和配置一致。

## 学习资源

### 官方文档
- [MyBatis-Plus 官方文档](https://baomidou.com/)
- [Spring Boot 官方文档](https://spring.io/projects/spring-boot)
- [MyBatis 官方文档](https://mybatis.org/mybatis-3/)

### 进阶学习
- [MyBatis-Plus 源码解析](https://github.com/baomidou/mybatis-plus)
- [Spring Boot 最佳实践](https://spring.io/guides)
- [数据库设计规范](https://dev.mysql.com/doc/)

## 贡献指南

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 联系方式

- 作者：Example
- 邮箱：example@example.com
- 项目地址：https://github.com/example/mybatis-plus-demo

---

**注意**：这是一个教学示例项目，仅用于学习 MyBatis-Plus 的使用方法。在生产环境中使用时，请根据实际需求进行适当的安全配置和性能优化。