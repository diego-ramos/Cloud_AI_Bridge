# Azure Deployment Guide

This document covers the complete deployment process for Cloud AI Bridge to Azure.

## Prerequisites

- Azure account (Pay-As-You-Go or free trial)
- Azure CLI installed: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli

---

## Step 1: Register Required Providers

```bash
az login
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.DocumentDB
```

---

## Step 2: Create Resource Group

```bash
az group create --name pdf-extractor --location eastus
```

---

## Step 3: Create Azure Cosmos DB

### 3.1 Create Cosmos DB Account

```bash
az cosmosdb create --name py-pdf-extractor-db --resource-group pdf-extractor --locations regionName=eastus
```

### 3.2 Get Connection Details

```bash
# Get the endpoint
az cosmosdb show --name py-pdf-extractor-db --resource-group pdf-extractor --query documentEndpoint

# Get the primary key
az cosmosdb keys list --name py-pdf-extractor-db --resource-group pdf-extractor --query primaryMasterKey
```

### 3.3 Create Database

```bash
az cosmosdb sql database create --name cloud_ai_bridge --account-name py-pdf-extractor-db --resource-group pdf-extractor
```

### 3.4 Create Container

```bash
az cosmosdb sql container create --name customer_instructions --database-name cloud_ai_bridge --account-name py-pdf-extractor-db --resource-group pdf-extractor --partition-key-path /id
```

---

## Step 4: Create Azure Container Registry (ACR)

```bash
az acr create --resource-group pdf-extractor --name pypdfextractor --sku Standard --location eastus
```

### 4.1 Enable ACR Admin and Get Credentials

```bash
# Enable admin user
az acr update --name pypdfextractor --admin-enabled true

# Get credentials (save these!)
az acr credential show --name pypdfextractor
```

---

## Step 5: Build and Push Docker Image

```bash
cd "c:\Purchase_orders_WorkSpace\Cloud_AI_Bridge"
az acr build --registry pypdfextractor --image py-pdf-extractor:latest --file Dockerfile .
```

---

## Step 6: Create Container Apps Environment

First, check your resource group location:

```bash
az group show --name pdf-extractor --query location -o tsv
```

Then create the environment:

```bash
az containerapp env create --name py-pdf-extractor-env --resource-group pdf-extractor --location eastus
```

---

## Step 7: Deploy Container App

Replace the placeholders with actual values:

```bash
az containerapp create \
  --name py-pdf-extractor \
  --resource-group pdf-extractor \
  --image pypdfextractor.azurecr.io/py-pdf-extractor:latest \
  --environment py-pdf-extractor-env \
  --cpu 0.5 --memory 1Gi \
  --min-replicas 1 --max-replicas 1 \
  --target-port 8080 \
  --ingress external \
  --transport http \
  --registry-server pypdfextractor.azurecr.io \
  --registry-username pypdfextractor \
  --registry-password "YOUR_ACR_PASSWORD" \
  --env-vars "PORT=8080" "OPEN_AI_END_POINT=https://py-pdf-extractor.openai.azure.com/" "OPEN_AI_KEY=YOUR_OPENAI_KEY" "API_KEY=secret-php-api-key" "COSMOS_ENDPOINT=https://py-pdf-extractor-db.documents.azure.com:443/" "COSMOS_KEY=YOUR_COSMOS_KEY" "COSMOS_DB_NAME=cloud_ai_bridge" "COSMOS_CONTAINER_NAME=customer_instructions"
```

**Important:**
- Use `--target-port` only (not `--port`)
- Include `PORT=8080` in `--env-vars`
- Include `--registry-server`, `--registry-username`, `--registry-password` for ACR authentication

---

## Step 8: Verify Deployment

```bash
az containerapp revision list --name py-pdf-extractor --resource-group pdf-extractor -o table
```

Expected: HealthState = Healthy, ProvisioningState = Provisioned

---

## Step 9: Get the Public URL

```bash
az containerapp show --name py-pdf-extractor --resource-group pdf-extractor --query properties.configuration.ingress.fqdn -o tsv
```

Your app will be available at:
```
https://py-pdf-extractor.ashywater-3c07aa7f.eastus.azurecontainerapps.io
```

---

## Updating the Application

After making code changes:

```bash
# Rebuild the image
az acr build --registry pypdfextractor --image py-pdf-extractor:latest --file Dockerfile .

# Update the container app
az containerapp update --name py-pdf-extractor --resource-group pdf-extractor --image pypdfextractor.azurecr.io/py-pdf-extractor:latest
```

---

## Environment Variables Reference

| Variable | Description | Required |
|----------|-------------|----------|
| `PORT` | Container port (must be 8080) | Yes |
| `API_KEY` | Bearer token for authentication | Yes |
| `OPEN_AI_END_POINT` | Azure OpenAI endpoint URL | Yes |
| `OPEN_AI_KEY` | Azure OpenAI API key | Yes |
| `AZURE_OPENAI_API_VERSION` | API version (default: 2024-12-01-preview) | No |
| `AZURE_BASE_MODEL` | Base model (default: gpt-4o-mini) | No |
| `AZURE_PRO_MODEL` | PRO model (default: gpt-4o) | No |
| `COSMOS_ENDPOINT` | Cosmos DB endpoint | Yes |
| `COSMOS_KEY` | Cosmos DB access key | Yes |
| `COSMOS_DB_NAME` | Database name (default: cloud_ai_bridge) | No |
| `COSMOS_CONTAINER_NAME` | Container name (default: customer_instructions) | No |

---

## Testing the Deployment

```bash
# Test extraction
curl -X POST https://py-pdf-extractor.eastus.azurecontainerapps.io/extract_pdf \
  -H "Authorization: Bearer secret-php-api-key" \
  -H "Content-Type: application/json" \
  -d '{"pdf_base64":"BASE64_ENCODED_PDF","customer_id":"your_customer_id"}'
```

---

## Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `unrecognized arguments: --port` | Using `--port` instead of `--target-port` | Use `--target-port` only |
| `UNAUTHORIZED` pulling image | ACR auth not configured | Add `--registry-*` flags on create |
| Container crashing | App startup error | Run image locally with `docker run` to see logs |
| `'' is not a valid port number` | PORT env var missing | Add `PORT=8080` to `--env-vars` |
| Environment does not exist | Env not created yet | Run `az containerapp env create` first |

---

## Troubleshooting

### Check container logs
```bash
az containerapp logs show --name py-pdf-extractor --resource-group pdf-extractor --tail 100
```

### Check container status
```bash
az containerapp show --name py-pdf-extractor --resource-group pdf-extractor
```

### Restart the container
```bash
az containerapp revision restart --name py-pdf-extractor --resource-group pdf-extractor
```