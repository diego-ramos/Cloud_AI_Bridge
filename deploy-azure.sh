#!/bin/bash
# Deploy to Azure Container Apps

# Configuration
RESOURCE_GROUP="pdf-extractor"
CONTAINER_APP_NAME="py-pdf-extractor"
CONTAINER_IMAGE="py-pdf-extractor:latest"
LOCATION="eastus"

echo "=== Deploying to Azure Container Apps ==="

# 1. Create Container Apps environment (if needed)
echo "Step 1: Creating Container Apps environment..."
az containerapp env create \
  --name py-pdf-extractor-env \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION

# 2. Build and push container to ACR (or use existing)
echo "Step 2: Building container..."
az acr build \
  --registry pyPdfExtractor \
  --image $CONTAINER_IMAGE \
  --file Dockerfile .

# 3. Deploy to Container Apps
echo "Step 3: Deploying to Container Apps..."
az containerapp create \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --image pyPdfExtractor.azurecr.io/$CONTAINER_IMAGE \
  --environment py-pdf-extractor-env \
  --cpu 0.5 --memory 1Gi \
  --min-replicas 1 --max-replicas 1 \
  --port 8080 \
  --target-port 8080 \
  --ingress external \
  --transport http \
  --env-vars "OPEN_AI_END_POINT=https://py-pdf-extractor.openai.azure.com/" "OPEN_AI_KEY=YOUR_KEY_HERE" "API_KEY=YOUR_API_KEY" "COSMOS_ENDPOINT=https://py-pdf-extractor-db.documents.azure.com:443/" "COSMOS_KEY=YOUR_COSMOS_KEY" "COSMOS_DB_NAME=cloud_ai_bridge" "COSMOS_CONTAINER_NAME=customer_instructions"

echo "=== Deployment Complete ==="
echo "Your app will be available at:"
echo "https://$CONTAINER_APP_NAME.$LOCATION.azurecontainerapps.io/extract_pdf"