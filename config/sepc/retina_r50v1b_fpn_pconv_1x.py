from models.retinanet.builder import RetinaNet as Detector
from models.NASFPN.builder import ResNetV1bFPN as Backbone
from models.sepc.builder import RetinaNetNeckWithBNWithSEPC as Neck
from models.sepc.builder import RetinaNetHeadWithBNWithSEPC as RpnHead
from mxnext.complicate import normalizer_factory


def get_config(is_train):
    class General:
        log_frequency = 100
        name = __name__.rsplit("/")[-1].rsplit(".")[-1]
        batch_image = 4 if is_train else 1
        fp16 = True


    class KvstoreParam:
        kvstore     = "nccl"
        batch_image = General.batch_image
        gpus        = [0, 1, 2, 3, 4, 5, 6, 7]
        fp16        = General.fp16


    class NormalizeParam:
        normalizer = normalizer_factory(type="syncbn",  ndev=len(KvstoreParam.gpus), wd_mult=1.0, lr_mult=1.0, eps=1e-4, mom=0.997)


    class BackboneParam:
        fp16 = General.fp16
        normalizer = NormalizeParam.normalizer
        depth = 50

    class NeckParam:
        fp16 = General.fp16
        normalizer = NormalizeParam.normalizer

    class SEPCParam:
        out_channels = 256
        pconv_num = 4
        start_level = 1
        pconv_deform = False 
        ibn = False
        lcconv_deform = False
        pad_sizes = (800,1333)
        stride = (8, 16, 32, 64, 128)

    class RpnParam:
        num_class   = 1 + 80
        fp16 = General.fp16
        normalizer = NormalizeParam.normalizer
        batch_image = General.batch_image
        nb_conv = 0

        class anchor_generate:
            scale = (4 * 2 ** 0, 4 * 2 ** (1.0 / 3.0), 4 * 2 ** (2.0 / 3.0))
            ratio = (0.5, 1.0, 2.0)
            stride = (8, 16, 32, 64, 128)
            image_anchor = None

        class head:
            conv_channel = 256
            mean = None
            std = None
            assert conv_channel == SEPCParam.out_channels

        class proposal:
            pre_nms_top_n = 1000
            post_nms_top_n = None
            nms_thr = None
            min_bbox_side = None
            min_det_score = 0.05 # filter score in network

        class focal_loss:
            alpha = 0.25
            gamma = 2.0


    class BboxParam:
        fp16        = General.fp16
        normalizer  = NormalizeParam.normalizer
        num_class   = None
        image_roi   = None
        batch_image = None


    class RoiParam:
        fp16 = General.fp16
        normalizer = NormalizeParam.normalizer
        out_size = None
        stride = None


    class DatasetParam:
        if is_train:
            image_set = ("coco_train2017", )
        else:
            image_set = ("coco_val2017", )

    backbone = Backbone(BackboneParam)
    neck = Neck(NeckParam, SEPCParam)
    rpn_head = RpnHead(RpnParam)
    detector = Detector()
    if is_train:
        train_sym = detector.get_train_symbol(backbone, neck, rpn_head)
        test_sym = None
    else:
        train_sym = None
        test_sym = detector.get_test_symbol(backbone, neck, rpn_head)


    class ModelParam:
        train_symbol = train_sym
        test_symbol = test_sym

        from_scratch = False
        random = True
        memonger = False
        memonger_until = "stage3_unit21_plus"

        class pretrain:
            prefix = "pretrain_model/resnet%s_v1b" % BackboneParam.depth
            epoch = 0
            fixed_param = ["conv0"]


    class OptimizeParam:
        class optimizer:
            type = "sgd"
            lr = 0.005 / 8 * len(KvstoreParam.gpus) * KvstoreParam.batch_image
            momentum = 0.9
            wd = 0.0001
            clip_gradient = None

        class schedule:
            begin_epoch = 0
            end_epoch = 6
            lr_iter = [60000 * 16 // (len(KvstoreParam.gpus) * KvstoreParam.batch_image),
                       80000 * 16 // (len(KvstoreParam.gpus) * KvstoreParam.batch_image)]

        class warmup:
            type = "gradual"
            lr = 0.005 / 8 * len(KvstoreParam.gpus) * KvstoreParam.batch_image / 3
            iter = 1000

    class TestParam:
        min_det_score = 0 # filter appended boxes
        max_det_per_image = 100

        process_roidb = lambda x: x
        process_output = lambda x, y: x

        class model:
            prefix = "experiments/{}/checkpoint".format(General.name)
            epoch = OptimizeParam.schedule.end_epoch

        class nms:
            type = "nms"
            thr = 0.5

        class coco:
            annotation = "data/coco/annotations/instances_val2017.json"

    # data processing
    class NormParam:
        mean = tuple(i * 255 for i in (0.485, 0.456, 0.406))
        std = tuple(i * 255 for i in (0.229, 0.224, 0.225))


    class ResizeParam:
        short = 800
        long = 1333


    class PadParam:
        short = 800
        long = 1333
        max_num_gt = 100


    class AnchorTarget2DParam:
        def __init__(self):
            self.generate = self._generate()

        class _generate:
            def __init__(self):
                self.short = (100, 50, 25, 13, 7)
                self.long = (167, 84, 42, 21, 11)
                self.stride = (8, 16, 32, 64, 128)

            scales = (4 * 2 ** 0, 4 * 2 ** (1.0 / 3.0), 4 * 2 ** (2.0 / 3.0))
            aspects = (0.5, 1.0, 2.0)

        class assign:
            allowed_border = 9999
            pos_thr = 0.5
            neg_thr = 0.4
            min_pos_thr = 0.0

        class sample:
            image_anchor = None
            pos_fraction = None


    class RenameParam:
        mapping = dict(image="data")


    from core.detection_input import ReadRoiRecord, Resize2DImageBbox, \
        ConvertImageFromHwcToChw, Flip2DImageBbox, Pad2DImageBbox, \
        RenameRecord
    from models.retinanet.input import PyramidAnchorTarget2D, Norm2DImage

    if is_train:
        transform = [
            ReadRoiRecord(None),
            Norm2DImage(NormParam),
            Resize2DImageBbox(ResizeParam),
            Flip2DImageBbox(),
            Pad2DImageBbox(PadParam),
            ConvertImageFromHwcToChw(),
            PyramidAnchorTarget2D(AnchorTarget2DParam()),
            RenameRecord(RenameParam.mapping)
        ]
        data_name = ["data"]
        label_name = ["rpn_cls_label", "rpn_reg_target", "rpn_reg_weight"]
    else:
        transform = [
            ReadRoiRecord(None),
            Norm2DImage(NormParam),
            Resize2DImageBbox(ResizeParam),
            Pad2DImageBbox(PadParam),
            ConvertImageFromHwcToChw(),
            RenameRecord(RenameParam.mapping)
        ]
        data_name = ["data", "im_info", "im_id", "rec_id"]
        label_name = []

    from models.retinanet import metric

    rpn_acc_metric = metric.FGAccMetric(
        "FGAcc",
        ["cls_loss_output"],
        ["rpn_cls_label"]
    )

    metric_list = [rpn_acc_metric]

    return General, KvstoreParam, RpnParam, RoiParam, BboxParam, DatasetParam, \
           ModelParam, OptimizeParam, TestParam, \
           transform, data_name, label_name, metric_list