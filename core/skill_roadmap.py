"""Módulo de Aceleração de Habilidades e Roteiro de Estudos para Lacunas Técnicas.

Transforma os requisitos faltantes (skills_missing) de uma vaga em um
plano de ação prático de 7 a 14 dias para o candidato dominar o essencial
e se destacar na entrevista técnica.
"""

from typing import List, Optional
from core.llm import LLMEngine
from core.models import CandidateProfile, Job


class SkillGapRoadmap:
    def __init__(self, profile: CandidateProfile, llm_engine: Optional[LLMEngine] = None):
        self.profile = profile
        self.llm = llm_engine or LLMEngine()

    def generate_roadmap(self, job: Job) -> str:
        """Gera um relatório de estudo acelerado em Markdown para as lacunas da vaga."""
        missing = job.skills_missing or []
        if not missing:
            # Tenta identificar termos comuns de tecnologia na vaga que não estão no perfil
            job_text = (job.title + " " + job.description).lower()
            known_techs = [
                "docker", "kubernetes", "aws", "gcp", "azure", "graphql", "redis",
                "kafka", "rabbitmq", "ci/cd", "terraform", "microservices", "next.js",
                "typescript", "react", "vue", "golang", "rust", "postgresql"
            ]
            my_skills_lower = [s.lower() for s in (self.profile.skills.primary + self.profile.skills.secondary)]
            missing = [t.title() for t in known_techs if t in job_text and t not in my_skills_lower][:4]

        missing_str = ", ".join(missing) if missing else "Aprofundamento Avançado da Stack Principal"

        prompt = f"""
Você é um Tech Lead e mentor sênior de carreiras de tecnologia.
O candidato está participando do processo seletivo para a vaga:
Cargo: {job.title} na empresa {job.company}

Perfil atual do candidato:
Habilidades que domina: {', '.join(self.profile.skills.primary)}
Tecnologias faltantes / gaps identificados: {missing_str}

Crie um "Plano de Aceleração Técnica & Sprint de 7 Dias" altamente prático e focado em aprovação na entrevista.

Estruture sua resposta ESTRITAMENTE em Markdown com as seguintes seções:
# 🚀 Plano de Aceleração Técnica: {job.title} @ {job.company}
## 🎯 1. Diagnóstico das Lacunas (O que a empresa realmente exige)
Explique o papel de cada tecnologia faltante ({missing_str}) no ecossistema da vaga.

## 📅 2. Sprint Prático de 7 Dias
- **Dias 1 e 2 (Conceitos Críticos & Arquitetura):** O que você precisa entender conceitualmente para não parecer amador.
- **Dias 3 e 4 (Mini-Projeto Hands-On Integrado):** Uma sugestão de projeto rápido de 4 horas conectando as tecnologias que o candidato já domina ({', '.join(self.profile.skills.primary[:2])}) com a ferramenta faltante ({missing_str}).
- **Dias 5 e 6 (Cenários Reais de Produção & Gotchas):** Armadilhas comuns, trade-offs e boas práticas que entrevistadores seniores adoram perguntar.
- **Dia 7 (Revisão & Pitch de Entrevista):** Consolidação dos pontos-chave.

## ❓ 3. Top 3 Perguntas Técnicas Prováveis de Entrevista
Apresente as perguntas que os avaliadores farão sobre esses tópicos e dê o roteiro de resposta ideal.

## 🛡️ 4. Script de Defesa Estratégica
Como responder com segurança e honestidade quando o entrevistador perguntar: *"Você já trabalhou com {missing_str} em produção no dia a dia?"*
Forneça um modelo de resposta transparente que transforme a falta de experiência corporativa formal em demonstração de rapidez de aprendizado e iniciativa.
"""
        ans = self.llm._generate_raw(prompt)
        if ans:
            return ans.strip()

        # Fallback determinístico caso não haja API configurada
        return self._generate_fallback_roadmap(job, missing)

    def _generate_fallback_roadmap(self, job: Job, missing_skills: List[str]) -> str:
        missing_text = ", ".join(missing_skills) if missing_skills else "Ferramentas Complementares da Vaga"
        primary_str = ", ".join(self.profile.skills.primary[:3])

        return f"""# 🚀 Plano de Aceleração Técnica: {job.title} @ {job.company}

> **Objetivo:** Dominar os fundamentos e defender com segurança as lacunas identificadas: **{missing_text}**.

---

## 🎯 1. Diagnóstico das Lacunas
A vaga exige familiaridade com **{missing_text}**. 
Em entrevistas técnicas, as empresas não esperam que você saiba todas as ferramentas de cor no primeiro dia, mas querem ter certeza de que você:
1. Compreende a **arquitetura e o propósito** da tecnologia (por que ela foi adotada em vez de alternativas simples).
2. Sabe lidar com **falhas, trade-offs e segurança básica**.
3. Tem capacidade de aprender rapidamente e integrar isso à sua stack consolidada (**{primary_str}**).

---

## 📅 2. Sprint Prático de 7 Dias

### 🔹 Dias 1 e 2: Fundamentos & Arquitetura
- Leia a documentação oficial ("Getting Started" e "Core Concepts") de cada uma das ferramentas faltantes.
- Entenda o fluxo de dados: como a informação entra, onde é processada e o que acontece quando falha.
- Anote 3 principais vantagens e 2 trade-offs/desvantagens dessas ferramentas.

### 🔹 Dias 3 e 4: Mini-Projeto Hands-On Integrado
- Crie um repositório no GitHub com uma aplicação mínima usando sua linguagem principal (**{self.profile.skills.primary[0] if self.profile.skills.primary else 'sua stack'}**).
- Conecte ou execute essa aplicação usando **{missing_text}**.
- Exemplo: se o gap for Docker/Containers, crie um `Dockerfile` multi-stage com cache otimizado e um `docker-compose.yml` conectando o banco de dados.
- Faça commit com mensagens semânticas bem documentadas no README.

### 🔹 Dias 5 e 6: Cenários Reais de Produção & Gotchas
- Pesquise: *"common pitfalls with {missing_text} in production"*.
- Descubra como monitorar métricas básicas (logs, consumo de memória, limites de conexões).
- Entenda a diferença entre rodar localmente vs rodar num ambiente corporativo de alta disponibilidade.

### 🔹 Dia 7: Simulação de Entrevista
- Treine explicar o projeto dos Dias 3 e 4 em voz alta em 2 minutos.
- Tenha clareza sobre quais foram os maiores desafios encontrados durante a implementação.

---

## ❓ 3. Perguntas Técnicas Prováveis de Entrevista
1. **"Por que usar {missing_text} em vez de uma abordagem tradicional?"**
   - *Foco da resposta:* Ganho de escalabilidade, padronização de ambiente, desacoplamento e facilidade de manutenção.
2. **"Quais são os principais desafios ou armadilhas ao adotar essa tecnologia?"**
   - *Foco da resposta:* Complexidade operacional inicial, necessidade de observabilidade adequada e gerenciamento de estado/persistência.
3. **"Como você garantiria a segurança e a integridade dos dados ao trabalhar com isso?"**
   - *Foco da resposta:* Princípio do menor privilégio, segregação de credenciais via variáveis de ambiente/secrets vault e testes automatizados.

---

## 🛡️ 4. Script de Defesa Estratégica na Entrevista
Quando o entrevistador fizer a pergunta:  
*"Você já usou {missing_text} no dia a dia em produção?"*

**Sua resposta recomendada:**
> *"Embora nos meus últimos projetos formais a arquitetura tenha priorizado soluções com as quais eu já tinha profunda senioridade (como {primary_str}), eu acompanho de perto a evolução do mercado. Recentemente montei um ambiente prático e desenvolvi um projeto integrando {missing_text} com {self.profile.skills.primary[0] if self.profile.skills.primary else 'meu backend'}, justamente para validar os conceitos de arquitetura, trade-offs e resolução de problemas. Por conta da minha base sólida em engenharia de software, minha curva de adaptação para o ambiente produtivo da {job.company} é extremamente rápida."*
"""
