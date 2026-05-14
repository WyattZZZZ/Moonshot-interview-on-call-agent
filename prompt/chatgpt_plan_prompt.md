我刚刚又收到一个moonshot的笔试邀请，我需要你根据题目和我讨论架构方案

---

题目如下：# 编程面试：On-Call 助手 ...

---

我倾向于不使用rag，我的策略是使用sqlite+向量属性组成semantic search部分，然后我需要你帮我确定在这个框架中使用elasticsearch是不是太重了，我打算做一套均分搜索系统，按照词频和语义一起检索

---

我打算这么设计，对于v1，bm25，维护一个sqlite，新加入文件时统计词频，存入sqlite，使用restful api： post v1/documents
get v1/documents/id
delete
等等你自己列举，然后get v1/search就行
v1/就是一个简单的搜索框

对于v2同样的设计，使用sqlite+introduction embedding属性，不分chunk，自动生成introduction存储在sqlite中并向量化，其余与v1保持同步，前段与v1共享一个界面，用户可以在同一个界面上点击不同的tab切换

v3就是一个agent，前端做成简易对话样式，展示工具调用过程，逻辑写在后端，只有一个api就是chat

三个版本共用一个env文件，到时候我发给面试官后让他自己填api key啥的

---

好的，总结文件: api接口文档（三个版本），开发流程phase todolist文档