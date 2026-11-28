REGISTRY ?= 192.168.199.123:2233
IMAGE_NAMESPACE ?= homeops
IMAGE_TAG ?= latest

BACKEND_IMAGE ?= $(REGISTRY)/$(IMAGE_NAMESPACE)/homeops-backend:$(IMAGE_TAG)
FRONTEND_IMAGE ?= $(REGISTRY)/$(IMAGE_NAMESPACE)/homeops-frontend:$(IMAGE_TAG)

DOCKER ?= docker
COMPOSE ?= docker compose

.PHONY: build build-backend build-frontend push push-backend push-frontend release deploy

build: build-backend build-frontend

build-backend:
	$(DOCKER) build -f docker/backend/Dockerfile -t $(BACKEND_IMAGE) backend

build-frontend:
	$(DOCKER) build -f docker/frontend/Dockerfile -t $(FRONTEND_IMAGE) frontend

push: push-backend push-frontend

push-backend:
	$(DOCKER) push $(BACKEND_IMAGE)

push-frontend:
	$(DOCKER) push $(FRONTEND_IMAGE)

release: build push

deploy:
	$(COMPOSE) pull
	$(COMPOSE) up -d
