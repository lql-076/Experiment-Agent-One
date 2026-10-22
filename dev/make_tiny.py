"""造极小的假底座和假嵌入模型（几 MB），在没有显卡的地方测本地模型服务。需要 torch、transformers、peft。
用法：python dev/make_tiny.py 输出文件夹"""
import os, sys, torch
from tokenizers import Tokenizer, models, trainers, pre_tokenizers, decoders
from transformers import PreTrainedTokenizerFast, LlamaConfig, LlamaForCausalLM, Qwen3Config, Qwen3Model
from peft import LoraConfig, get_peft_model
out = sys.argv[1]
text = ["你好，我是测试。今天天气不错，提醒我晚上十点吃药。", "Hello world, this is a tiny tokenizer for testing.", "帮我查一下帕鲁最近更新了什么", "记住我的鞋码是43"] * 50
tok = Tokenizer(models.BPE(unk_token="<unk>"))
tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
tok.decoder = decoders.ByteLevel()
tr = trainers.BpeTrainer(vocab_size=600, special_tokens=["<unk>", "<s>", "</s>", "<pad>", "<|im_start|>", "<|im_end|>"], initial_alphabet=pre_tokenizers.ByteLevel.alphabet())
tok.train_from_iterator(text, tr)
ft = PreTrainedTokenizerFast(tokenizer_object=tok, unk_token="<unk>", bos_token="<s>", eos_token="</s>", pad_token="<pad>")
ft.chat_template = "{% for m in messages %}<|im_start|>{{ m['role'] }}\n{{ m['content'] }}<|im_end|>\n{% endfor %}{% if add_generation_prompt %}<|im_start|>assistant\n{% if not enable_thinking %}<think>\n\n</think>\n{% endif %}{% endif %}"
V = len(ft)
base = os.path.join(out, "base"); emb = os.path.join(out, "embed"); lora = os.path.join(out, "brains", "测试小脑")
torch.manual_seed(0)
m = LlamaForCausalLM(LlamaConfig(vocab_size=V, hidden_size=64, intermediate_size=128, num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=512, pad_token_id=ft.pad_token_id, eos_token_id=ft.eos_token_id, bos_token_id=ft.bos_token_id))
m.save_pretrained(base); ft.save_pretrained(base)
e = Qwen3Model(Qwen3Config(vocab_size=V, hidden_size=64, intermediate_size=128, num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2, head_dim=16, max_position_embeddings=512))
e.save_pretrained(emb); ft.save_pretrained(emb)
pm = get_peft_model(LlamaForCausalLM.from_pretrained(base), LoraConfig(r=4, target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM"))
pm.save_pretrained(lora)
print("made", V, os.listdir(base), os.listdir(lora))
