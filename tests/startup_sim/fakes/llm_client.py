"""Fake llm_client: a llama-server with load time, prefill/generation speed and n_ctx.

wait_for_ready() is upstream's logic verbatim (health check, then sleep).
Answers carry the mode as a tag word (TIPS / SURVIVE / RECIPE), so the
simulation can tell which mode produced whatever is being spoken.
"""
import re
from types import SimpleNamespace as NS

import simworld as S
from simworld import mode_of


class ConnectError(Exception):
    pass


class HTTPStatusError(Exception):
    pass


def _tok(s):
    return max(1, len(s) // 4)


def _answer(mode, user, n_words, newlines=True):
    """A small instruct model answers a how-to question as a short list more
    often than not, so by default every sentence is its own line."""
    topic = ' '.join(re.findall(r'[a-z]+', user.lower())[-3:]) or 'that'
    sents, n = [], 0
    k = 0
    while n < n_words:
        k += 1
        s = f'{mode} point {k} about {topic}, keep it simple and stay safe out there.'
        sents.append(s)
        n += len(s.split())
    return ('\n' if newlines else ' ').join(sents)


RECIPE = ("<<RECIPE>>\nRECIPE Campfire tuna pasta\nTime: 30 min\nIngredients:\n- 200 g pasta\n"
          "- 1 can tuna\n- 1 onion\nSteps:\n1. Boil water over open flame, 10 min.\n"
          "2. Cook pasta 9 min until soft.\n3. Fry onion on embers 5 min.\n4. Mix in tuna and serve.")


class _Models:
    def list(self):
        if not S.W.chat_ready():
            raise ConnectError('chat server down')
        return NS(data=[NS(id='LFM2.5-1.2B-Instruct-Q4_K_M.gguf', owned_by='llamacpp')])


class _Completions:
    def create(self, model=None, messages=None, stream=False, **extra):
        W = S.W
        if not W.chat_ready():
            raise ConnectError('[sim] chat server not reachable')
        msgs = [dict(m) for m in messages]
        n_ctx = W.cfg.get('n_ctx', 4096)
        prompt_tokens = sum(_tok(m['content']) + 6 for m in msgs)
        if not stream:
            # The warm-up: the README's 4.0 s for a whole short reply; the
            # first token alone (prefill + one step) takes about a quarter.
            S.sleep(W.jit(1.0 if extra.get('max_tokens') == 1 else 4.0, 'llm_warmup'))
            return NS(choices=[NS(message=NS(content='Hello!'))])
        rec = {'t': round(S.now(), 2), 'mode': mode_of(msgs[0]['content']), 'tokens': prompt_tokens,
               'roles': [m['role'] for m in msgs],
               'msgs': [(m['role'], m['content'][:70]) for m in msgs]}
        W.llm_requests.append(rec)
        if len(W.llm_requests) in W.cfg.get('fail_requests', []):
            rec['error'] = 'server_error'
            raise HTTPStatusError('500 Internal Server Error (simulated one-off failure)')
        if prompt_tokens > n_ctx and W.cfg.get('ctx_mode', 'error') == 'error':
            rec['error'] = 'exceed_context_size'
            raise HTTPStatusError(f"400 Bad Request: the request exceeds the available context size "
                                  f"({prompt_tokens} > {n_ctx} tokens)")
        mode = rec['mode']
        user = msgs[-1]['content'].split('User question: ')[-1]
        if mode == 'RECIPE' and user.startswith('My ingredients:'):
            text = RECIPE
        elif mode == 'RECIPE':
            text = 'RECIPE what else do you have with you?'
        else:
            text = _answer(mode, user, W.cfg.get('answer_words', 45), W.cfg.get('answer_newlines', True))
        new_tokens = _tok(msgs[-1]['content']) + (_tok(msgs[0]['content']) if len(msgs) <= 2 else 0)
        ttft = W.jit(0.4 + new_tokens / 70.0, 'ttft')

        def gen():
            S.sleep(ttft)
            room = n_ctx - prompt_tokens
            for i, piece in enumerate(re.findall(r'\S+\s*', text)):
                if i * 1.3 > room:
                    break                      # context full: generation stops
                if not W.chat_ready():
                    raise ConnectError('[sim] chat server went away mid-stream')
                S.sleep(1.3 / 7.0)             # ~7 tokens/s
                yield NS(choices=[NS(delta=NS(content=piece))])
        return gen()


class LLMClient:
    def __init__(self, base_url, api_key='dummy'):
        self.base_url = base_url
        self.models = _Models()
        self.chat = NS(completions=_Completions())

    def health(self):
        S.sleep(0.02)
        return S.W.chat_ready()

    def wait_for_ready(self, max_retries=30, retry_delay=2.0):
        for attempt in range(max_retries):
            if self.health():
                return True
            print(f">> Waiting for LLM server at {self.base_url}... ({attempt + 1}/{max_retries})")
            S.sleep(retry_delay)
        raise ConnectionError(f"LLM server at {self.base_url} not ready after {max_retries} attempts")

    def close(self):
        pass
