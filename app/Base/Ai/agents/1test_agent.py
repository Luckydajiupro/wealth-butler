from app.Base.Ai.agents import NL2CypherAgent
from app.Base.Ai.middlewares import LoggingMiddleware, MetricsMiddleware, SafetyMiddleware
from app.Base.Client.neo4jClient import Neo4jClient

agent = NL2CypherAgent(client=Neo4jClient(), middlewares=[LoggingMiddleware(),
                                                          MetricsMiddleware(),
                                                          SafetyMiddleware(), ])





if __name__ == '__main__':
    agent.run("张三投资了黄金和白银")