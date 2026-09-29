"""
MediAssist QLoRA Training Script

Trains a single LoRA adapter on BioMistral 7B using QLoRA (4-bit quantization).
Compatible with Azure ML curated environment (Python 3.8, older package versions).

Usage:
  python train_adapter.py --adapter_type triage --data_path /path/to/data.jsonl
  python train_adapter.py --adapter_type discharge --data_path /path/to/data.jsonl
  python train_adapter.py --adapter_type patient --data_path /path/to/data.jsonl
"""

import os
import re
import json
import argparse
import torch
from datasets import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

# Try importing mlflow - may not be available
try:
    import mlflow
    HAS_MLFLOW = True
except ImportError:
    HAS_MLFLOW = False

# Try importing evaluate for ROUGE
try:
    import evaluate
    HAS_EVALUATE = True
except ImportError:
    HAS_EVALUATE = False


# --- Adapter configurations ---
ADAPTER_CONFIGS = {
    "triage": {
        "filter_values": ["TRIAGE_NOTE"],
        "system_prompt": (
            "You are a clinical triage assistant for Emergency Departments. "
            "Given patient symptoms, vitals, and history, generate a structured "
            "triage decision note with CTAS/MTS priority level, clinical reasoning, "
            "and recommended actions."
        ),
        "output_dir": "./outputs/triage_adapter",
        "max_length": 1024,
    },
    "discharge": {
        "filter_values": ["DISCHARGE_SUMMARY"],
        "system_prompt": (
            "You are a clinical documentation assistant. Given triage notes and "
            "clinical findings, generate a structured discharge summary including "
            "diagnosis, investigations, treatment given, and GP follow-up recommendations."
        ),
        "output_dir": "./outputs/discharge_adapter",
        "max_length": 1536,
    },
    "patient": {
        "filter_values": ["CLINICAL_NOTE"],
        "system_prompt": (
            "You are a patient communication assistant. Translate clinical medical "
            "text into plain English that a person with a 6th grade reading level "
            "can understand. Avoid medical jargon. Use simple, clear sentences."
        ),
        "output_dir": "./outputs/patient_adapter",
        "max_length": 768,
    },
}

# --- Model configuration ---
#MODEL_ID = "BioMistral/BioMistral-7B"
MODEL_ID = "BioMistral/BioMistral-Safetensors"

# --- QLoRA configuration ---
QLORA_CONFIG = {
    "r": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "v_proj", "k_proj", "o_proj"],
    "bias": "none",
    "task_type": "CAUSAL_LM",
}


def load_and_filter_data(data_path, adapter_type):
    """Load JSONL data and filter by task tag in instruction field."""
    config = ADAPTER_CONFIGS[adapter_type]

    records = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line.strip())
            instruction = record.get("instruction", "")
            match = re.search(r'\[TASK:\s*([^\]]+)\]', instruction)
            task_tag = match.group(1) if match else ""

            if task_tag in config["filter_values"]:
                records.append(record)

    print("Loaded {} records for {} adapter".format(len(records), adapter_type))

    if len(records) == 0:
        raise ValueError(
            "No records found for adapter '{}' with task tags {}. Check your JSONL data.".format(
                adapter_type, config["filter_values"]
            )
        )

    return Dataset.from_list(records)


def format_prompt(record, adapter_type):
    """Format a record into Alpaca-style prompt for training."""
    config = ADAPTER_CONFIGS[adapter_type]

    instruction = record.get("instruction", "")
    input_text = record.get("input", "")
    output_text = record.get("output", "")

    prompt = "### System:\n{}\n\n### Instruction:\n{}\n\n### Input:\n{}\n\n### Response:\n{}".format(
        config["system_prompt"], instruction, input_text, output_text
    )

    return prompt


def train(adapter_type, data_path, num_epochs=3, batch_size=4):
    """Main training function."""
    config = ADAPTER_CONFIGS[adapter_type]

    print("")
    print("=" * 60)
    print("Training {} adapter".format(adapter_type))
    print("Model: {}".format(MODEL_ID))
    print("QLoRA: rank={}, alpha={}".format(QLORA_CONFIG["r"], QLORA_CONFIG["lora_alpha"]))
    print("Epochs: {}, Batch size: {}".format(num_epochs, batch_size))
    print("=" * 60)
    print("")

    # Start MLflow run if available
    if HAS_MLFLOW:
        mlflow.start_run(run_name="{}-adapter-training".format(adapter_type))
        mlflow.log_params({
            "adapter_type": adapter_type,
            "model_id": MODEL_ID,
            "lora_r": QLORA_CONFIG["r"],
            "lora_alpha": QLORA_CONFIG["lora_alpha"],
            "num_epochs": num_epochs,
            "batch_size": batch_size,
        })

    # Load and filter data
    print("Loading data...")
    dataset = load_and_filter_data(data_path, adapter_type)

    # Format prompts
    print("Formatting prompts...")
    formatted = dataset.map(
        lambda x: {"text": format_prompt(x, adapter_type)},
        remove_columns=dataset.column_names,
    )

    # Split into train/eval
    split = formatted.train_test_split(test_size=0.1, seed=42)
    train_dataset = split["train"]
    eval_dataset = split["test"]

    print("Train samples: {}".format(len(train_dataset)))
    print("Eval samples: {}".format(len(eval_dataset)))

    if HAS_MLFLOW:
        mlflow.log_metrics({
            "train_samples": len(train_dataset),
            "eval_samples": len(eval_dataset),
        })

    # Load tokenizer
    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # BitsAndBytes 4-bit config
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    # Load model in 4-bit
    print("Loading BioMistral 7B in 4-bit quantization...")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        use_safetensors=True,
    )

    # Prepare for QLoRA training
    model = prepare_model_for_kbit_training(model)
    model.config.use_cache = False

    # Apply LoRA
    print("Applying LoRA adapter...")
    lora_config = LoraConfig(**QLORA_CONFIG)
    model = get_peft_model(model, lora_config)

    # Print trainable parameters
    trainable, total = model.get_nb_trainable_parameters()
    print("Trainable parameters: {:,} / {:,} ({:.2f}%)".format(
        trainable, total, 100 * trainable / total
    ))

    if HAS_MLFLOW:
        mlflow.log_metric("trainable_params", trainable)
        mlflow.log_metric("total_params", total)

    # Training arguments - compatible with older transformers
    training_args = TrainingArguments(
        output_dir=config["output_dir"],
        num_train_epochs=num_epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.1,
        weight_decay=0.01,
        logging_steps=10,
        evaluation_strategy="steps",
        eval_steps=50,
        save_strategy="steps",
        save_steps=100,
        save_total_limit=2,
        fp16=True,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        max_grad_norm=0.3,
        group_by_length=True,
        dataloader_pin_memory=False,
        report_to= "none",
    )

    # Create trainer
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        tokenizer=tokenizer,
        dataset_text_field="text",
        max_seq_length=config["max_length"],
    )

    # Train
    print("")
    print("Starting training...")
    train_result = trainer.train()

    # Log final metrics
    print("Training loss: {:.4f}".format(train_result.training_loss))

    if HAS_MLFLOW:
        mlflow.log_metrics({
            "final_train_loss": train_result.training_loss,
            "train_runtime_seconds": train_result.metrics["train_runtime"],
            "train_samples_per_second": train_result.metrics["train_samples_per_second"],
        })

    # Evaluate
    print("")
    print("Running evaluation...")
    eval_results = trainer.evaluate()
    print("Eval loss: {:.4f}".format(eval_results["eval_loss"]))

    if HAS_MLFLOW:
        mlflow.log_metric("eval_loss", eval_results["eval_loss"])

    # Compute ROUGE scores on eval subset
    if HAS_EVALUATE:
        print("Computing ROUGE scores...")
        try:
            rouge = evaluate.load("rouge")
            eval_subset = eval_dataset.select(range(min(30, len(eval_dataset))))
            predictions = []
            references = []

            for sample in eval_subset:
                parts = sample["text"].split("### Response:")
                if len(parts) == 2:
                    input_text = parts[0] + "### Response:\n"
                    reference = parts[1].strip()

                    inputs = tokenizer(
                        input_text,
                        return_tensors="pt",
                        truncation=True,
                        max_length=512,
                    ).to(model.device)

                    with torch.no_grad():
                        outputs = model.generate(
                            **inputs,
                            max_new_tokens=256,
                            temperature=0.3,
                            do_sample=True,
                        )

                    pred = tokenizer.decode(
                        outputs[0][inputs["input_ids"].shape[1]:],
                        skip_special_tokens=True,
                    )
                    predictions.append(pred)
                    references.append(reference)

            if predictions:
                rouge_results = rouge.compute(
                    predictions=predictions,
                    references=references,
                    use_stemmer=True,
                )
                print("ROUGE-1: {:.4f}".format(rouge_results["rouge1"]))
                print("ROUGE-2: {:.4f}".format(rouge_results["rouge2"]))
                print("ROUGE-L: {:.4f}".format(rouge_results["rougeL"]))

                if HAS_MLFLOW:
                    mlflow.log_metrics({
                        "rouge1": round(rouge_results["rouge1"], 4),
                        "rouge2": round(rouge_results["rouge2"], 4),
                        "rougeL": round(rouge_results["rougeL"], 4),
                    })
        except Exception as e:
            print("ROUGE computation skipped: {}".format(e))

    # Save adapter weights
    print("")
    print("Saving adapter to {}...".format(config["output_dir"]))
    os.makedirs(config["output_dir"], exist_ok=True)
    trainer.save_model(config["output_dir"])
    tokenizer.save_pretrained(config["output_dir"])

    # Log adapter as MLflow artifact
    if HAS_MLFLOW:
        mlflow.log_artifacts(config["output_dir"], artifact_path="{}_adapter".format(adapter_type))
        mlflow.end_run()

    print("")
    print("=" * 60)
    print("{} adapter training complete!".format(adapter_type))
    print("Adapter saved to: {}".format(config["output_dir"]))
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train MediAssist LoRA adapter")
    parser.add_argument(
        "--adapter_type",
        type=str,
        required=True,
        choices=["triage", "discharge", "patient"],
        help="Which adapter to train: triage, discharge, or patient",
    )
    parser.add_argument(
        "--data_path",
        type=str,
        required=True,
        help="Path to mtsamples_training_data.jsonl",
    )
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=4, help="Training batch size")

    args = parser.parse_args()
    train(args.adapter_type, args.data_path, args.epochs, args.batch_size)