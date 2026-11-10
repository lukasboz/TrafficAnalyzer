"""YOLOX COCO detection and line-crossing tracking. No identity recognition."""
import threading
import urllib.request
import cv2
import numpy as np
import onnxruntime as ort
from scipy.optimize import linear_sum_assignment
from .config import MODEL, MODEL_URL

VEHICLES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


class Detector:
    def __init__(self):
        self.session = None
        self.lock = threading.Lock()
        self.error = None

    def load(self):
        with self.lock:
            if self.session is not None:
                return
            try:
                if not MODEL.exists():
                    target = MODEL.with_suffix(".download")
                    urllib.request.urlretrieve(MODEL_URL, target)
                    target.replace(MODEL)
                options = ort.SessionOptions()
                options.intra_op_num_threads = 2
                self.session = ort.InferenceSession(str(MODEL), options, providers=["CPUExecutionProvider"])
                self.input = self.session.get_inputs()[0]
                self.height, self.width = self.input.shape[2:]
                self.error = None
            except Exception as exc:
                self.error = str(exc)
                raise

    def detect(self, frame, threshold=0.3, roi=(0,0,1,1)):
        self.load()
        h, w = frame.shape[:2]
        ratio = min(self.height / h, self.width / w)
        padded = np.full((self.height,self.width,3),114,dtype=np.uint8)
        padded[:int(h*ratio),:int(w*ratio)] = cv2.resize(frame,(int(w*ratio),int(h*ratio)))
        tensor = np.ascontiguousarray(padded.transpose(2,0,1), dtype=np.float32)[None]
        out = self.session.run(None, {self.input.name: tensor})[0][0]
        # Official YOLOX ONNX export leaves grid/stride decoding to the caller.
        grids, strides = [], []
        for stride in (8,16,32):
            gy, gx = np.meshgrid(np.arange(self.height//stride),np.arange(self.width//stride),indexing="ij")
            grid = np.stack((gx,gy),-1).reshape(-1,2)
            grids.append(grid)
            strides.append(np.full((len(grid),1),stride))
        grid = np.concatenate(grids)
        stride = np.concatenate(strides)
        out[:,:2] = (out[:,:2] + grid) * stride
        out[:,2:4] = np.exp(np.clip(out[:,2:4],-20,20)) * stride
        cls = np.argmax(out[:,5:], axis=1)
        scores = out[:,4] * out[np.arange(len(out)),cls+5]
        mask = np.isin(cls,list(VEHICLES)) & (scores>=threshold)
        selected = out[mask,:4] / ratio
        scores, cls = scores[mask], cls[mask]
        xy = selected[:,:2] - selected[:,2:4]/2
        boxes = np.concatenate((xy,selected[:,2:4]),axis=1)
        detections=[]
        # Class-agnostic NMS prevents overlapping vehicle labels being counted twice.
        keep=cv2.dnn.NMSBoxes(boxes.tolist(),scores.tolist(),threshold,0.45)
        for index in np.asarray(keep).flatten():
            x,y,bw,bh = boxes[index]
            x1,y1,x2,y2 = np.clip([x/w,y/h,(x+bw)/w,(y+bh)/h],0,1)
            cx,cy=(x1+x2)/2,(y1+y2)/2
            if not (roi[0] <= cx <= roi[2] and roi[1] <= cy <= roi[3]):
                continue
            detections.append({"box": [float(x1),float(y1),float(x2),float(y2)], "class": VEHICLES[int(cls[index])], "confidence": round(float(scores[index]),3)})
        return detections


def occupancy(detections, roi):
    mask = np.zeros((200,200),dtype=np.uint8)
    for d in detections:
        x1,y1,x2,y2=d["box"]
        mask[int(y1*200):int(y2*200),int(x1*200):int(x2*200)] = 1
    x1,y1,x2,y2 = [int(v*200) for v in roi]
    region=mask[y1:y2,x1:x2]
    return float(region.mean()*100) if region.size else 0.0


def center(box):
    return np.array([(box[0]+box[2])/2,(box[1]+box[3])/2])


def iou(a,b):
    x1,y1=max(a[0],b[0]),max(a[1],b[1])
    x2,y2=min(a[2],b[2]),min(a[3],b[3])
    overlap=max(0,x2-x1)*max(0,y2-y1)
    return overlap/max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-overlap)


class Tracker:
    def __init__(self, gate):
        self.gate = np.array(gate,dtype=float).reshape(2,2)
        self.tracks={}
        self.next_id=1
        self.total=0
        self.direction={"a_to_b":0,"b_to_a":0}
        self.classes={v:0 for v in VEHICLES.values()}

    def side(self, point):
        a,b=self.gate
        edge,offset=b-a,point-a
        signed=float(edge[0]*offset[1]-edge[1]*offset[0]) / max(np.linalg.norm(edge),1e-6)
        return 1 if signed>0.012 else (-1 if signed< -0.012 else 0)

    def intersects(self, previous, current):
        a,b=self.gate
        v=current-previous
        matrix=np.column_stack((v,-(b-a)))
        if abs(np.linalg.det(matrix))<1e-8:
            return False
        t,u=np.linalg.solve(matrix,a-previous)
        return 0<=t<=1 and 0<=u<=1

    def update(self,detections,elapsed):
        # Expire lost tracks before matching to avoid reusing identities.
        self.tracks={k:v for k,v in self.tracks.items() if elapsed-v["time"]<=1.8}
        tracks=list(self.tracks.values())
        costs=np.full((len(tracks),len(detections)),10.0)
        for i,t in enumerate(tracks):
            for j,d in enumerate(detections):
                distance=np.linalg.norm(center(t["box"])-center(d["box"]))
                if distance<0.14 and d["class"]==t["class"]:
                    costs[i,j]=distance + (1-iou(t["box"],d["box"]))*0.1
        matches={}
        if costs.size:
            rows,cols=linear_sum_assignment(costs)
            matches={int(c):tracks[r] for r,c in zip(rows,cols) if costs[r,c]<0.23}
        crossed=0
        for j,d in enumerate(detections):
            point=center(d["box"])
            side=self.side(point)
            t=matches.get(j)
            if t is None:
                t={"id":self.next_id,"side":side,"anchor":point,"hits":0,"counted":False,"class":d["class"]}
                self.next_id+=1
                self.tracks[t["id"]]=t
            t["hits"]+=1
            if side and t["side"] and side!=t["side"] and not t["counted"] and t["hits"]>=2:
                if self.intersects(t["anchor"],point):
                    t["counted"]=True
                    crossed+=1
                    self.total+=1
                    self.classes[d["class"]]+=1
                    self.direction["a_to_b" if t["side"]==-1 else "b_to_a"]+=1
            if side:
                t["side"]=side
                t["anchor"]=point
            t.update(box=d["box"],time=elapsed)
            d["track_id"]=t["id"]
        return crossed


detector=Detector()
