# PaDiM GUI launcher

import os
import cv2
import numpy
import shutil
import sys
import glob
import ailia

from PIL import Image, ImageTk

sys.path.append('../../util')
from padim_utils import *
from model_utils import check_and_download_models  # noqa: E402
import webcamera_utils  # noqa: E402

# for macOS, please install "brew install python-tk@3.9"
import tkinter as tk
from tkinter import ttk
import tkinter.filedialog

import log_init
from logging import getLogger  # noqa: E402

from utils import get_base_parser, update_parser  # noqa: E402

logger = getLogger(__name__)

parser = get_base_parser('PaDiM GUI', None, None)
args = update_parser(parser)

# ======================
# Global settings
# ======================

input_index = 0
output_index = 0
result_index = 0
slider_index = 50

REMOTE_PATH = 'https://storage.googleapis.com/ailia-models/padim/'

train_folder = None
test_folder = None
test_type = "folder"

score_cache = {}

# ======================
# Environment
# ======================

def input_changed(event):
    global input_index
    selection = event.widget.curselection()
    if selection:
        input_index = selection[0]
    else:
        input_index = 0   
    load_detail(train_list[input_index])

def output_changed(event):
    global output_index
    selection = event.widget.curselection()
    if selection:
        output_index = selection[0]
    else:
        output_index = 0   
    load_detail(test_list[output_index])

def result_changed(event):
    global result_index
    selection = event.widget.curselection()
    if selection:
        result_index = selection[0]
    else:
        result_index = 0   
    load_detail(result_list[result_index])

def slider_changed(event):
    global scale, slider_index
    slider_index = scale.get()

# ======================
# Change file
# ======================

CANVAS_W = 480
CANVAS_H = 160

def create_photo_image(path,w=CANVAS_W,h=CANVAS_H):
    image_bgr = cv2.imread(path)
    if image_bgr is None:
        capture = cv2.VideoCapture(path)
        ret, image_bgr = capture.read()
        capture.release()
    #image_bgr = cv2.resize(image_bgr,(w,h))
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB) # imreadはBGRなのでRGBに変換
    image_pil = Image.fromarray(image_rgb) # RGBからPILフォーマットへ変換
    image_pil.thumbnail((w,h), Image.ANTIALIAS)
    image_tk  = ImageTk.PhotoImage(image_pil) # ImageTkフォーマットへ変換
    return image_tk

def load_canvas_image(path):
    global canvas, canvas_item, image_tk
    image_tk = create_photo_image(path)
    if canvas_item == None:
        canvas_item = canvas.create_image(0, 0, image=image_tk, anchor=tk.NW)
    else:
        canvas.itemconfig(canvas_item,image=image_tk)

def load_detail(image_path):
    image_exist = False
    for ext in [".jpg",".png"]:
        if os.path.exists(image_path):
            load_canvas_image(image_path)
            image_exist = True
            break


# ======================
# Run model
# ======================

def get_keep_aspect():
    global valueKeepAspect
    return valueKeepAspect.get()

def get_image_resize():
    global valueCenterCrop
    image_resize = 224
    if valueCenterCrop.get():
        image_resize = 256
    return image_resize

def train_button_clicked():
    global train_folder
    print("begin training")

    # model files check and download
    weight_path, model_path, params = get_params("resnet18")
    check_and_download_models(weight_path, model_path, REMOTE_PATH)

    # create net instance
    net = ailia.Net(model_path, weight_path, env_id=args.env_id)

    # training
    batch_size = 32
    train_dir = train_folder
    if train_dir == "camera":
        global train_list, input_index
        train_dir = train_list[input_index].split(":")[1]
    aug = False
    aug_num = 0
    seed = 1024
    train_outputs = training(net, params, get_image_resize(), get_keep_aspect(), batch_size, train_dir, aug, aug_num, seed, logger)

    # save learned distribution
    train_feat_file = "train.pkl"
    #train_dir = args.train_dir
    #train_feat_file = "%s.pkl" % os.path.basename(train_dir)
    logger.info('saving train set feature to: %s ...' % train_feat_file)
    with open(train_feat_file, 'wb') as f:
        pickle.dump(train_outputs, f)
    logger.info('saved.')

    score_cache = {}

def test_button_clicked():
    global score_cache
    global valueKeepAspect, valueCenterCrop
    print("begin test")

    if "keep_aspect" in score_cache:
        if score_cache["keep_aspect"] != get_keep_aspect() or score_cache["image_resize"] != get_image_resize():
            score_cache = {}
    score_cache["keep_aspect"] = get_keep_aspect()
    score_cache["image_resize"] = get_image_resize()

    # model files check and download
    weight_path, model_path, params = get_params("resnet18")
    check_and_download_models(weight_path, model_path, REMOTE_PATH)

    # create net instance
    env_id = ailia.get_gpu_environment_id()
    net = ailia.Net(model_path, weight_path, env_id=env_id)

    # load trained model
    with open("train.pkl", 'rb') as f:
        train_outputs = pickle.load(f)
    
    threshold = slider_index / 100.0

    if test_type == "folder":
        test_from_folder(net, params, train_outputs, threshold)
    else:
        test_from_video(net, params, train_outputs, threshold)

def test_from_folder(net, params, train_outputs, threshold):
    # file loop
    test_imgs = []

    score_map = []
    for i_img in range(0, len(test_list)):
        logger.info('from (%s) ' % (test_list[i_img]))

        image_path = test_list[i_img]
        img = load_image(image_path)
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
        img = preprocess(img, get_image_resize(), keep_aspect=get_keep_aspect())

        test_imgs.append(img[0])
        if image_path in score_cache:
            dist_tmp = score_cache[image_path].copy()
        else:
            dist_tmp = infer(net, params, train_outputs, img)
            score_cache[image_path] = dist_tmp.copy()
        score_map.append(dist_tmp)

    scores = normalize_scores(score_map)
    anormal_scores = calculate_anormal_scores(score_map)

    # Plot gt image
    os.makedirs("result", exist_ok=True)
    global result_list, listsResult, ListboxResult
    result_list = []
    for i in range(0, scores.shape[0]):
        img = denormalization(test_imgs[i])
        heat_map, mask, vis_img = visualize(img, scores[i], threshold)
        frame = pack_visualize(heat_map, mask, vis_img, scores)
        dirname, path = os.path.split(test_list[i])
        output_path = "result/"+path
        cv2.imwrite(output_path, frame)       
        result_list.append(output_path)

    listsResult.set(result_list)
    load_detail(result_list[0])
    ListboxResult.select_set(0)

def test_from_video(net, params, train_outputs, threshold):
    result_path = "result.mp4"

    video_path = test_folder
    if video_path == "camera":
        global test_list, output_index
        video_path = test_list[output_index].split(":")[1]

    capture = webcamera_utils.get_capture(video_path)
    f_h = int(IMAGE_SIZE)
    f_w = int(IMAGE_SIZE) * 3
    writer = webcamera_utils.get_writer(result_path, f_h, f_w)

    score_map = []

    frame_shown = False
    while(True):
        ret, frame = capture.read()
        if (cv2.waitKey(1) & 0xFF == ord('q')) or not ret:
            break
        if frame_shown and cv2.getWindowProperty('frame', cv2.WND_PROP_VISIBLE) == 0:
            break

        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = preprocess(img, get_image_resize(), keep_aspect=get_keep_aspect())

        dist_tmp = infer(net, params, train_outputs, img)

        score_map.append(dist_tmp)
        scores = normalize_scores(score_map)    # min max is calculated dynamically, please set fixed min max value from calibration data for production

        heat_map, mask, vis_img = visualize(denormalization(img[0]), scores[len(scores)-1], threshold)
        frame = pack_visualize(heat_map, mask, vis_img, scores)

        cv2.imshow('frame', frame)
        frame_shown = True

        if writer is not None:
            writer.write(frame)

    capture.release()
    cv2.destroyAllWindows()
    if writer is not None:
        writer.release()

    global result_list, listsResult, ListboxResult
    result_list = [result_path]
    listsResult.set(result_list)
    load_detail(result_list[0])
    ListboxResult.select_set(0)

# ======================
# Select file
# ======================

train_folder = "train"
test_folder = None

def train_file_dialog():
    global listsInput, ListboxInput, input_index
    global train_folder
    global train_list
    fTyp = [("Image File or Video File", "*")]
    iDir = os.path.abspath(os.path.dirname(__file__))
    file_name = tk.filedialog.askopenfilename(filetypes=fTyp, initialdir=iDir)
    if len(file_name) != 0:
        train_folder = file_name
        train_list = [file_name]
        listsInput.set(train_list)
        train_index = 0
        ListboxInput.select_set(0)
        load_detail(train_list[0])

def train_folder_dialog():
    global listsInput, ListboxInput, input_index
    global train_folder
    global train_list
    iDir = os.path.abspath(os.path.dirname(__file__))
    file_name = tk.filedialog.askdirectory(initialdir=iDir)
    if len(file_name) != 0:
        train_folder = file_name
        train_list = get_training_file_list()
        listsInput.set(train_list)
        train_index = 0
        ListboxInput.select_set(0)
        if len(train_list)>=1:
            load_detail(train_list[0])

def train_camera_dialog():
    global listsInput, ListboxInput, input_index
    global train_folder
    global train_list
    train_folder = "camera"
    train_list = get_camera_list()
    listsInput.set(train_list)
    train_index = 0
    ListboxInput.select_set(0)
    load_detail(train_list[0])

def test_file_dialog():
    global listsOutput, ListboxOutput, output_index
    global test_folder
    global test_list
    global test_type
    fTyp = [("Image File or Video File", "*")]
    iDir = os.path.abspath(os.path.dirname(__file__))
    file_name = tk.filedialog.askopenfilename(filetypes=fTyp, initialdir=iDir)
    if len(file_name) != 0:
        test_folder = file_name
        test_list = [file_name]
        listsOutput.set(test_list)
        test_index = 0
        ListboxOutput.select_set(0)
        if len(test_list)>=1:
            load_detail(test_list[0])
        test_type = "video"

def test_folder_dialog():
    global listsOutput, ListboxOutput, output_index
    global test_folder
    global test_list
    global test_type
    iDir = os.path.abspath(os.path.dirname(__file__))
    file_name = tk.filedialog.askdirectory(initialdir=iDir)
    if len(file_name) != 0:
        test_folder = file_name
        test_list = get_test_file_list()
        listsOutput.set(test_list)
        test_index = 0
        ListboxOutput.select_set(0)
        load_detail(test_list[0])
        test_type = "folder"

def test_camera_dialog():
    global listsOutput, ListboxOutput, output_index
    global test_folder
    global test_list
    global test_type
    test_folder = "camera"
    test_list = get_camera_list()
    listsOutput.set(test_list)
    test_index = 0
    ListboxOutput.select_set(0)
    load_detail(test_list[0])
    test_type = "videp"

def get_camera_list():
    index = 0
    inputs = []
    while True:
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            inputs.append("camera:"+str(index))
        else:
            break
        index=index+1
        cap.release()
    return inputs

def get_file_list(folder):
    base_path = folder+"/"
    files = glob.glob(base_path+"*.jpg")
    files.extend(glob.glob(base_path+"*.png"))
    files.extend(glob.glob(base_path+"*.bmp"))
    image_list = []
    for image_path in files:
        image_list.append(image_path)
    image_list.sort()
    return image_list

def get_training_file_list():
    global train_folder
    return get_file_list(train_folder)

def get_test_file_list():
    global test_folder
    if test_folder!=None:
        return get_file_list(test_folder)
    return ["bottle_000.png"]

def get_result_file_list():
    return []

# ======================
# GUI
# ======================

canvas_item = None

def main():
    global train_list, test_list, result_list
    global listsResult, ListboxResult
    global canvas, scale
    global inputFile, listsInput, input_list, ListboxInput
    global outputFile, listsOutput, output_list, ListboxOutput
    global valueKeepAspect, valueCenterCrop

    # rootメインウィンドウの設定
    root = tk.Tk()
    root.title("PaDiM GUI")
    root.geometry("1200x600")

    # メインフレームの作成と設置
    frame = ttk.Frame(root)
    frame.pack(padx=20,pady=10)

    # Listboxの選択肢
    train_list = get_training_file_list()
    test_list = get_test_file_list()
    result_list = get_result_file_list()

    listsInput = tk.StringVar(value=train_list)
    listsOutput = tk.StringVar(value=test_list)
    listsResult = tk.StringVar(value=result_list)

    # 各種ウィジェットの作成
    ListboxInput = tk.Listbox(frame, listvariable=listsInput, width=20, height=12, selectmode="single", exportselection=False)
    ListboxOutput = tk.Listbox(frame, listvariable=listsOutput, width=20, height=12, selectmode="single", exportselection=False)
    ListboxResult = tk.Listbox(frame, listvariable=listsResult, width=20, height=12, selectmode="single", exportselection=False)

    ListboxInput.bind("<<ListboxSelect>>", input_changed)
    ListboxOutput.bind("<<ListboxSelect>>", output_changed)
    ListboxResult.bind("<<ListboxSelect>>", result_changed)

    ListboxInput.select_set(input_index)
    ListboxOutput.select_set(output_index)
    ListboxResult.select_set(result_index)

    textRun = tk.StringVar(frame)
    textRun.set("Train")

    textStop = tk.StringVar(frame)
    textStop.set("Test")

    textTrainFolder = tk.StringVar(frame)
    textTrainFolder.set("Open folder")

    textTrainVideo = tk.StringVar(frame)
    textTrainVideo.set("Open video")

    textTrainCamera = tk.StringVar(frame)
    textTrainCamera.set("Open camera")

    textTestFolder = tk.StringVar(frame)
    textTestFolder.set("Open folder")

    textTestVideo = tk.StringVar(frame)
    textTestVideo.set("Open video")

    textTestCamera = tk.StringVar(frame)
    textTestCamera.set("Open camera")

    textInput = tk.StringVar(frame)
    textInput.set("Train images")

    textOutput = tk.StringVar(frame)
    textOutput.set("Test images")

    textResult = tk.StringVar(frame)
    textResult.set("Result images")

    textModelDetail = tk.StringVar(frame)
    textModelDetail.set("Preview")

    textCheckbox = tk.StringVar(frame)
    textCheckbox.set("Train settings")

    textTestSettings = tk.StringVar(frame)
    textTestSettings.set("Test settings")

    textSlider = tk.StringVar(frame)
    textSlider.set("threshold")

    valueKeepAspect = tkinter.BooleanVar()
    valueKeepAspect.set(True)
    valueCenterCrop = tkinter.BooleanVar()
    valueCenterCrop.set(True)
    chkKeepAspect = tk.Checkbutton(frame, variable=valueKeepAspect, text='keep aspect')
    chkCenterCrop = tk.Checkbutton(frame, variable=valueCenterCrop, text='center crop')

    # 各種ウィジェットの作成
    labelInput = tk.Label(frame, textvariable=textInput)
    labelOutput = tk.Label(frame, textvariable=textOutput)
    labelResult = tk.Label(frame, textvariable=textResult)
    labelModelDetail = tk.Label(frame, textvariable=textModelDetail)
    labelCheckbox = tk.Label(frame, textvariable=textCheckbox)
    labelTestSettings = tk.Label(frame, textvariable=textTestSettings)
    labelSlider = tk.Label(frame, textvariable=textSlider)

    buttonTrain = tk.Button(frame, textvariable=textRun, command=train_button_clicked, width=14)
    buttonTest = tk.Button(frame, textvariable=textStop, command=test_button_clicked, width=14)

    buttonTrainFolder = tk.Button(frame, textvariable=textTrainFolder, command=train_folder_dialog, width=14)
    buttonTrainVideo = tk.Button(frame, textvariable=textTrainVideo, command=train_file_dialog, width=14)
    buttonTrainCamera = tk.Button(frame, textvariable=textTrainCamera, command=train_camera_dialog, width=14)

    buttonTestFolder = tk.Button(frame, textvariable=textTestFolder, command=test_folder_dialog, width=14)
    buttonTestVideo = tk.Button(frame, textvariable=textTestVideo, command=test_file_dialog, width=14)
    buttonTestCamera = tk.Button(frame, textvariable=textTestCamera, command=test_camera_dialog, width=14)

    canvas = tk.Canvas(frame, bg="black", width=CANVAS_W, height=CANVAS_H)
    canvas.place(x=0, y=0)

    load_detail(test_list[0])

    var_scale = tk.DoubleVar()
    var_scale.set(slider_index)
    scale = tk.Scale(
        frame,
        variable=var_scale,
        orient=tk.HORIZONTAL,
        tickinterval=20,
        length=200,
    )
    scale.bind("<ButtonRelease-1>", slider_changed)

    # 各種ウィジェットの設置
    labelInput.grid(row=0, column=0, sticky=tk.NW, rowspan=1)
    ListboxInput.grid(row=1, column=0, sticky=tk.NW, rowspan=4)
    buttonTrainFolder.grid(row=6, column=0, sticky=tk.NW)
    buttonTrainVideo.grid(row=7, column=0, sticky=tk.NW)
    buttonTrainCamera.grid(row=8, column=0, sticky=tk.NW)

    labelOutput.grid(row=0, column=1, sticky=tk.NW)
    ListboxOutput.grid(row=1, column=1, sticky=tk.NW, rowspan=4)
    buttonTestFolder.grid(row=6, column=1, sticky=tk.NW)
    buttonTestVideo.grid(row=7, column=1, sticky=tk.NW)
    buttonTestCamera.grid(row=8, column=1, sticky=tk.NW)

    labelResult.grid(row=0, column=2, sticky=tk.NW)
    ListboxResult.grid(row=1, column=2, sticky=tk.NW, rowspan=4)

    labelModelDetail.grid(row=0, column=3, sticky=tk.NW, columnspan=3)
    canvas.grid(row=1, column=3, sticky=tk.NW, rowspan=4, columnspan=3)

    buttonTrain.grid(row=6, column=3, sticky=tk.NW)
    buttonTest.grid(row=6, column=4, sticky=tk.NW)

    labelCheckbox.grid(row=8, column=3, sticky=tk.NW)
    chkKeepAspect.grid(row=9, column=3,  sticky=tk.NW)
    chkCenterCrop.grid(row=10, column=3,  sticky=tk.NW)

    labelTestSettings.grid(row=8, column=4, sticky=tk.NW, columnspan=3)
    labelSlider.grid(row=9, column=4, sticky=tk.NW, columnspan=3)
    scale.grid(row=10, column=4, sticky=tk.NW, columnspan=3)

    # メインフレームの作成と設置
    frame = ttk.Frame(root)
    frame.pack(padx=20, pady=10)

    root.mainloop()

if __name__ == '__main__':
    main()



