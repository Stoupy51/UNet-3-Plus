"""
Training script
"""
from datetime import datetime
import hydra
from omegaconf import DictConfig
import tensorflow as tf
from keras.callbacks import (
    EarlyStopping,
    ModelCheckpoint,
    TensorBoard,
    CSVLogger
)

import data_generator
from data_preparation.verify_data import verify_data
from utils.general_utils import create_directory, join_paths, set_gpus, get_gpus_count
from models.model import prepare_model
from losses.loss import dice_coef
from losses.unet_loss import unet3p_hybrid_loss


def create_training_folders(cfg: DictConfig):
    """
    Create directories to store Model CheckPoint and TensorBoard logs.
    """
    create_directory(
        join_paths(
            cfg.WORK_DIR,
            cfg.CALLBACKS.MODEL_CHECKPOINT.PATH
        )
    )
    create_directory(
        join_paths(
            cfg.WORK_DIR,
            cfg.CALLBACKS.TENSORBOARD.PATH
        )
    )


def train(cfg: DictConfig):
    """
    Training method
    """

    print("Verifying data ...")
    verify_data(cfg)

    if cfg.MODEL.TYPE == "unet3plus_deepsup_cgm":
        raise ValueError(
            "UNet3+ with Deep Supervision and Classification Guided Module"
            "\nModel exist but training script is not supported for this variant"
            "please choose other variants from config file"
        )

    if cfg.USE_MULTI_GPUS.VALUE:
        # change number of visible gpus for training
        set_gpus(cfg.USE_MULTI_GPUS.GPU_IDS)
        # change batch size according to available gpus
        gpu_count = get_gpus_count()
        if gpu_count > 1:
            cfg.HYPER_PARAMETERS.BATCH_SIZE = cfg.HYPER_PARAMETERS.BATCH_SIZE * gpu_count

    # create folders to store training checkpoints and logs
    create_training_folders(cfg)

    # data generators
    train_generator = data_generator.DataGenerator(cfg, mode="TRAIN")
    val_generator = data_generator.DataGenerator(cfg, mode="VAL")

    # verify generator
    # for i, (batch_images, batch_mask) in enumerate(val_generator):
    #     print(len(batch_images))
    #     if i >= 3: break

    # optimizer
    # TODO update optimizer
    optimizer = tf.keras.optimizers.Adam(
        learning_rate=cfg.HYPER_PARAMETERS.LEARNING_RATE
    )

    # create model
    if cfg.USE_MULTI_GPUS.VALUE:
        # multi gpu training using tensorflow mirrored strategy
        strategy = tf.distribute.MirroredStrategy(
            cross_device_ops=tf.distribute.HierarchicalCopyAllReduce()
        )
        print('Number of visible gpu devices: {}'.format(strategy.num_replicas_in_sync))
        with strategy.scope():
            model = prepare_model(cfg, training=True)
    else:
        model = prepare_model(cfg, training=True)

    model.compile(
        optimizer=optimizer,
        loss=unet3p_hybrid_loss,
        metrics=[dice_coef],
    )
    model.summary()

    # the tensorboard log directory will be a unique subdirectory
    # based on the start time for the run
    tb_log_dir = join_paths(
        cfg.WORK_DIR,
        cfg.CALLBACKS.TENSORBOARD.PATH,
        "{}".format(datetime.now().strftime("%Y.%m.%d.%H.%M.%S"))
    )
    print("TensorBoard directory\n" + tb_log_dir)

    checkpoint_path = join_paths(
        cfg.WORK_DIR,
        cfg.CALLBACKS.MODEL_CHECKPOINT.PATH,
        f"{cfg.MODEL.WEIGHTS_FILE_NAME}.hdf5"
    )
    print("Weights path\n" + checkpoint_path)

    csv_log_path = join_paths(
        cfg.WORK_DIR,
        cfg.CALLBACKS.CSV_LOGGER.PATH,
        f"training_logs_{cfg.MODEL.TYPE}.csv"
    )
    print("Logs path\n" + csv_log_path)

    # evaluation metric
    evaluation_metric = "val_dice_coef"
    if len(model.outputs) > 1:
        evaluation_metric = f"val_{model.output_names[0]}_dice_coef"

    # TensorBoard, EarlyStopping, ModelCheckpoint and CSVLogger callbacks
    callbacks = [
        TensorBoard(log_dir=tb_log_dir, write_graph=False, profile_batch=0),
        EarlyStopping(
            patience=cfg.CALLBACKS.EARLY_STOPPING.PATIENCE,
            verbose=cfg.VERBOSE
        ),
        ModelCheckpoint(
            checkpoint_path,
            verbose=cfg.VERBOSE,
            save_weights_only=cfg.CALLBACKS.MODEL_CHECKPOINT.SAVE_WEIGHTS_ONLY,
            save_best_only=cfg.CALLBACKS.MODEL_CHECKPOINT.SAVE_BEST_ONLY,
            monitor=evaluation_metric,
            mode="max"

        ),
        CSVLogger(
            csv_log_path,
            append=cfg.CALLBACKS.CSV_LOGGER.APPEND_LOGS
        )
    ]

    training_steps = train_generator.__len__()
    validation_steps = val_generator.__len__()

    # start training
    model.fit(
        x=train_generator,
        steps_per_epoch=training_steps,
        validation_data=val_generator,
        validation_steps=validation_steps,
        epochs=cfg.HYPER_PARAMETERS.EPOCHS,
        batch_size=cfg.HYPER_PARAMETERS.BATCH_SIZE,
        callbacks=callbacks,
        workers=cfg.DATALOADER_WORKERS,
    )


@hydra.main(version_base=None, config_path="configs", config_name="config")
def main(cfg: DictConfig):
    """
    Read config file and pass to train method for training
    """
    train(cfg)


if __name__ == "__main__":
    main()
