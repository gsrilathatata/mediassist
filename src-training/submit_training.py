"""
MediAssist Azure ML Training Submission

Submits 3 QLoRA training jobs to Azure ML:
  1. triage_adapter
  2. discharge_adapter
  3. patient_adapter

Each job runs on the gpu-training-cluster using the
mediassist-training environment.

Usage:
  python submit_training.py --all           (submit all 3)
  python submit_training.py --adapter triage (submit one)
"""

import argparse
from azure.ai.ml import MLClient, command, Input
from azure.ai.ml.entities import Environment
from azure.identity import DefaultAzureCredential


# --- Configuration ---
SUBSCRIPTION_ID = "your-subscription-id"  # Replace with your subscription ID
RESOURCE_GROUP = "your-resource-group"
WORKSPACE_NAME = "your-workspace-name"
COMPUTE_NAME = "gpu-training-cluster"

DATA_PATH = "azureml:your-subscription-id"

def get_client():
    """Connect to Azure ML workspace."""
    credential = DefaultAzureCredential()
    client = MLClient(
        credential=credential,
        subscription_id=SUBSCRIPTION_ID,
        resource_group_name=RESOURCE_GROUP,
        workspace_name=WORKSPACE_NAME,
    )
    print(f"Connected to workspace: {WORKSPACE_NAME}")
    return client


def create_environment(client):
    """Use Azure ML curated environment - no image build needed."""
    print("Using curated environment (no build required).")
    return None


def submit_training_job(client, adapter_type: str):
    """Submit a single adapter training job."""
    print(f"\nSubmitting {adapter_type} adapter training job...")

    job = command(
        code=".",
        command=(
            "pip install torch==2.1.2 torchvision --index-url https://download.pytorch.org/whl/cu118 --force-reinstall && "
            "pip install transformers==4.38.2 peft==0.9.0 trl==0.7.11 "
            "bitsandbytes==0.42.0 datasets==2.18.0 accelerate==0.27.2 "
            "sentencepiece protobuf safetensors evaluate rouge-score "
            "mlflow azureml-mlflow --force-reinstall && "
            "python -c \"import transformers; print(transformers.__version__)\" && "
            "python train_adapter.py "
            f"--adapter_type {adapter_type} "
            "--data_path ${{inputs.training_data}} "
            "--epochs 3 "
            "--batch_size 4"
        ),
        inputs={
            "training_data": Input(
                type="uri_file",
                path=DATA_PATH,
            )
        },
        environment="AzureML-ACPT-pytorch-1.13-py38-cuda11.7-gpu@latest",
        compute=COMPUTE_NAME,
        display_name=f"mediassist-{adapter_type}-adapter",
        description=f"QLoRA training for {adapter_type} adapter on BioMistral 7B",
        experiment_name="mediassist-adapter-training",
    )

    returned_job = client.jobs.create_or_update(job)
    print(f"Job submitted: {returned_job.name}")
    print(f"Status: {returned_job.status}")
    print(f"Studio URL: {returned_job.studio_url}")
    return returned_job


def main():
    parser = argparse.ArgumentParser(description="Submit MediAssist training jobs")
    parser.add_argument(
        "--adapter",
        type=str,
        choices=["triage", "discharge", "patient"],
        help="Train a specific adapter",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Train all 3 adapters sequentially",
    )
    args = parser.parse_args()

    if not args.adapter and not args.all:
        parser.print_help()
        return

    client = get_client()
    create_environment(client)

    if args.all:
        for adapter in ["triage", "discharge", "patient"]:
            job = submit_training_job(client, adapter)
            print(f"\nMonitor at: {job.studio_url}")
            print(f"Waiting for {adapter} to complete before starting next...")
            client.jobs.stream(job.name)
            print(f"{adapter} adapter training complete.\n")
    else:
        job = submit_training_job(client, args.adapter)
        print(f"\nMonitor at: {job.studio_url}")


if __name__ == "__main__":
    main()
