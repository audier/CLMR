import torch
from pytorch_lightning import LightningModule

from simclr import SimCLR
from simclr.modules import NT_Xent, LARS


class ContrastiveLearning(LightningModule):
    def __init__(self, args, encoder):
        super().__init__()
        self.save_hyperparameters(args)

        self.encoder = encoder
        self.n_features = (
            self.encoder.fc.in_features
        )  # get dimensions of last fully-connected layer
        self.model = SimCLR(self.encoder, self.hparams.projection_dim, self.n_features)
        self.criterion = self.configure_criterion()

    def forward(self, x_i, x_j):
        _, _, z_i, z_j = self.model(x_i, x_j)
        loss = self.criterion(z_i, z_j)
        return loss

    def training_step(self, batch, batch_idx):
        x, _ = batch
        x_i = x[:, 0, :].unsqueeze(dim=1)
        x_j = x[:, 1, :].unsqueeze(dim=1)
        loss = self.forward(x_i, x_j)
        self.log("Train/loss", loss)
        return loss

    def configure_criterion(self):
        # PT lightning aggregates differently in DP mode
        if self.hparams.accelerator == "dp" and self.hparams.gpus:
            batch_size = int(self.hparams.batch_size / self.hparams.gpus)
        else:
            batch_size = self.hparams.batch_size

        criterion = NT_Xent(batch_size, self.hparams.temperature, world_size=1)
        return criterion

    def configure_optimizers(self):
        scheduler = None
        if self.hparams.optimizer == "Adam":
            optimizer = torch.optim.Adam(self.model.parameters(), lr=3e-4)
        elif self.hparams.optimizer == "LARS":
            # optimized using LARS with linear learning rate scaling
            # (i.e. LearningRate = 0.3 × BatchSize/256) and weight decay of 10−6.
            learning_rate = 0.3 * self.hparams.batch_size / 256
            optimizer = LARS(
                self.model.parameters(),
                lr=learning_rate,
                weight_decay=self.hparams.weight_decay,
                exclude_from_weight_decay=["batch_normalization", "bias"],
            )

            # "decay the learning rate with the cosine decay schedule without restarts"
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
                optimizer, self.hparams.max_epochs, eta_min=0, last_epoch=-1
            )
        else:
            raise NotImplementedError

        if scheduler:
            return {"optimizer": optimizer, "lr_scheduler": scheduler}
        else:
            return {"optimizer": optimizer}
