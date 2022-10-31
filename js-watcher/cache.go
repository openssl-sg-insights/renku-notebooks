package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"path/filepath"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/selection"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/dynamic/dynamicinformer"
	"k8s.io/client-go/rest"
	k8sCache "k8s.io/client-go/tools/cache"
	"k8s.io/client-go/tools/clientcmd"
	"k8s.io/client-go/util/homedir"
)

// Cache is a light wrapper around a k8s informer for a single k8s namespace.
type Cache struct {
	lister      k8sCache.GenericLister
	informer    k8sCache.SharedInformer
	namespace   string
	userIDLabel string
}

// GenericResource allows unmarshalling the metadata of dynamic resources without
// unmarshalling their status and spec.
type GenericKubernetesResource struct {
	Metadata metav1.ObjectMeta `json:"metadata"`
	Spec     json.RawMessage   `json:"spec"`
	Status   json.RawMessage   `json:"status,omitempty"`

	metav1.TypeMeta `json:",inline"`
}

// synchronize synchronizes the the informer cache. It uses a channel that it will
// write to a boolean value to indicate whether the synchronization completed successfully
// (true) or it did not complete (false).
func (c *Cache) synchronize(ctx context.Context, doneCh chan bool) {
	if !k8sCache.WaitForCacheSync(ctx.Done(), c.informer.HasSynced) {
		log.Print("Could not sync informer cache with k8s.")
		doneCh <- false
	}
	doneCh <- true
}

// run runs the informer.
func (c *Cache) run(ctx context.Context) {
	c.informer.Run(ctx.Done())
}

func (c *Cache) getAll() (res []runtime.Object, err error) {
	res, err = c.lister.List(labels.NewSelector())
	if err != nil {
		return nil, fmt.Errorf("could not list servers for namespace %s: %w", c.namespace, err)
	}
	return res, nil
}

// getByUserID retrieves resources that belong to a specific user from the informer cache.
func (c *Cache) getByUserID(userID string) (res []runtime.Object, err error) {
	selector := labels.NewSelector()
	if userID != "" {
		requirement, err := labels.NewRequirement(c.userIDLabel, selection.Equals, []string{userID})
		if err != nil {
			return nil, fmt.Errorf("could not set up selector when looking for servers for userID %s: %w", userID, err)
		}
		selector = selector.Add(*requirement)
	}
	res, err = c.lister.List(selector)
	if err != nil {
		return nil, fmt.Errorf("could not list servers for userID %s: %w", userID, err)
	}
	return res, nil
}

// getByName retrieves a specific resource from the informer cache.
func (c *Cache) getByName(name string) (res runtime.Object, err error) {
	res, err = c.lister.Get(fmt.Sprintf("%s/%s", c.namespace, name))
	if err != nil {
		return nil, err
	}
	return res, nil
}

// getByNameAndUserID retrieves a specific resource (by name) that belongs to a specific
// user from the informer cache.
func (c *Cache) getByNameAndUserID(name string, userID string) (res runtime.Object, err error) {
	res, err = c.getByName(name)
	if err != nil {
		return nil, err
	}
	resUnstructured, err := runtime.DefaultUnstructuredConverter.ToUnstructured(res)
	if err != nil {
		return nil, fmt.Errorf("could not convert server %s to unstructured: %w", name, err)
	}
	resTyped := GenericKubernetesResource{}
	err = runtime.DefaultUnstructuredConverter.FromUnstructured(resUnstructured, &resTyped)
	if err != nil {
		return nil, fmt.Errorf("could not parse metadata on server %s: %w", name, err)
	}
	if resTyped.Metadata.Labels[c.userIDLabel] != userID {
		return nil, nil
	}
	return res, nil
}

func initializeK8sDynamicClient() (ks8DynamicClient dynamic.Interface, err error) {
	var clientConfig *rest.Config
	clientConfig, err = rest.InClusterConfig()
	if err != nil {
		log.Println("Cannot setup in-cluster config, looking for kubeconfig file")
		var kubeconfig *string
		if home := homedir.HomeDir(); home != "" {
			kubeconfig = flag.String("kubeconfig", filepath.Join(home, ".kube", "config"), "(optional) absolute path to the kubeconfig file")
		} else {
			kubeconfig = flag.String("kubeconfig", "", "absolute path to the kubeconfig file")
		}
		flag.Parse()

		clientConfig, err = clientcmd.BuildConfigFromFlags("", *kubeconfig)
		if err != nil {
			return nil, fmt.Errorf("cannot setup k8s client config: %w", err)
		}
	}
	ks8DynamicClient, err = dynamic.NewForConfig(clientConfig)
	if err != nil {
		return nil, fmt.Errorf("cannot setup k8s dynamic client: %w", err)
	}
	return ks8DynamicClient, nil
}

// NewCacheFromConfig generates a new server cache from a configuration and a specfic k8s namespace.
func NewCacheFromConfig(ctx context.Context, config Config, namespace string) (res *Cache, err error) {
	k8sDynamicClient, err := initializeK8sDynamicClient()
	if err != nil {
		return nil, err
	}
	resource := schema.GroupVersionResource{Group: config.CrGroup, Version: config.CrVersion, Resource: config.CrPlural}
	factory := dynamicinformer.NewFilteredDynamicSharedInformerFactory(k8sDynamicClient, time.Minute, namespace, nil)
	informer := factory.ForResource(resource).Informer()
	lister := factory.ForResource(resource).Lister()
	res = &Cache{informer: informer, lister: lister, namespace: namespace, userIDLabel: config.UserIDLabel}
	return res, nil
}
