"""Agente de navegação visual com marcação de elementos (Set-of-Marks / Multimodal).

Quando os seletores DOM convencionais falham em páginas altamente dinâmicas ou
ofuscadas, este módulo injeta marcadores numéricos nos elementos interativos e
utiliza a visão da IA (ou mapeamento espacial) para localizar e interagir com o campo correto.
"""

import base64
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
import requests
from playwright.sync_api import Page

from core.llm import LLMEngine

BASE_DIR = Path(__file__).resolve().parent.parent


class VisualFormAgent:
    def __init__(self, llm_engine: Optional[LLMEngine] = None):
        self.llm = llm_engine or LLMEngine()

    def annotate_interactive_elements(self, page: Page) -> List[Dict[str, any]]:
        """Injeta pequenas etiquetas numeradas nos elementos interativos da tela (Set-of-Marks)."""
        js_code = """
        () => {
            // Remove anotações anteriores se existirem
            document.querySelectorAll('.ai-visual-tag').forEach(e => e.remove());

            const targets = Array.from(document.querySelectorAll(
                'input:not([type="hidden"]), select, textarea, button, a[role="button"], div[role="checkbox"], div[role="button"]'
            )).filter(el => {
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
            });

            const elementsData = [];

            targets.forEach((el, idx) => {
                const id = idx + 1;
                const rect = el.getBoundingClientRect();

                // Cria o marcador visual
                const tag = document.createElement('div');
                tag.className = 'ai-visual-tag';
                tag.innerText = id;
                tag.style.position = 'absolute';
                tag.style.left = (window.scrollX + rect.left) + 'px';
                tag.style.top = (window.scrollY + rect.top) + 'px';
                tag.style.background = '#ef4444';
                tag.style.color = '#ffffff';
                tag.style.fontSize = '11px';
                tag.style.fontWeight = 'bold';
                tag.style.padding = '1px 4px';
                tag.style.borderRadius = '3px';
                tag.style.zIndex = '999999';
                tag.style.pointerEvents = 'none';
                tag.style.boxShadow = '0 1px 3px rgba(0,0,0,0.3)';
                document.body.appendChild(tag);

                elementsData.push({
                    id: id,
                    tag_name: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || '',
                    name: el.getAttribute('name') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    aria_label: el.getAttribute('aria-label') || '',
                    text: el.innerText ? el.innerText.trim().slice(0, 50) : '',
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2
                });
            });

            return elementsData;
        }
        """
        try:
            return page.evaluate(js_code)
        except Exception:
            return []

    def remove_annotations(self, page: Page):
        """Remove as marcações visuais da página."""
        try:
            page.evaluate("() => document.querySelectorAll('.ai-visual-tag').forEach(e => e.remove())")
        except Exception:
            pass

    def find_element_by_vision(
        self, page: Page, field_goal: str, elements_data: List[Dict[str, any]]
    ) -> Optional[int]:
        """Pergunta à IA multimodal qual o número da etiqueta que corresponde ao campo desejado."""
        if not elements_data:
            return None

        # Tira screenshot com as etiquetas visíveis
        screenshot_bytes = page.screenshot()
        b64_image = base64.b64encode(screenshot_bytes).decode("utf-8")

        prompt = f"""
Você é um agente de navegação visual web. 
Analise a imagem da tela onde cada elemento interativo possui uma pequena etiqueta vermelha numerada.
Objetivo: Precisamos encontrar o elemento correspondente ao campo: '{field_goal}'.

Aqui estão os dados textuais dos elementos detectados:
{json.dumps(elements_data[:40], ensure_ascii=False, indent=2)}

Responda ESTRITAMENTE em formato JSON com o seguinte schema:
{{
  "chosen_id": <número inteiro da etiqueta escolhida ou null se nenhum corresponder>
}}
"""
        # Se houver chave Gemini, utiliza a capacidade de visão multimodal
        if self.llm.gemini_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.llm.model}:generateContent?key={self.llm.gemini_key}"
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt},
                                {
                                    "inline_data": {
                                        "mime_type": "image/png",
                                        "data": b64_image,
                                    }
                                },
                            ]
                        }
                    ],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200},
                }
                resp = requests.post(url, json=payload, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    res_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    match = re.search(r"\{.*\}", res_text, re.DOTALL)
                    if match:
                        parsed = json.loads(match.group(0))
                        chosen = parsed.get("chosen_id")
                        if chosen and isinstance(chosen, int):
                            return chosen
            except Exception:
                pass

        # Fallback sem visão de IA: busca semântica direta nos dados textuais extraídos
        goal_lower = field_goal.lower()
        for el in elements_data:
            combined = f"{el.get('name', '')} {el.get('placeholder', '')} {el.get('aria_label', '')} {el.get('text', '')}".lower()
            if goal_lower in combined or any(w in combined for w in goal_lower.split()):
                return el["id"]

        return None
